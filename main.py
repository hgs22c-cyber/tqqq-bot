# -*- coding: utf-8 -*-
"""
main.py - 일일 실행 진입점
===========================
크론잡이 "미장 개장 +10분"에 하루 1번 이 파일을 실행한다.

동작 개요
---------
1) 오늘 이미 실행됐으면 스킵 (중복 실행 방지)
2) 계좌 잔고(보유수량/Pool) + TQQQ 현재가 조회
3) [사이클 시작일(Day 1) 또는 최초 실행]
     -> Step1~3 재계산(V, 밴드, 매수망/매도망) -> 전량 지정가 주문 전송
     -> state.json에 신규 사이클 상태 + 그리드 잔여분 저장
   [사이클 중간(Day 2~10)]
     -> 전일 대비 보유수량 변화로 "몇 개 그리드가 체결됐는지" 추정
     -> 체결된 만큼 그리드에서 제거, 잔여 그리드를 오늘자로 재주문
        (해외주식 지정가 주문은 하루 지나면 자동취소되므로 매일 재주문 필요)
4) 일일 로그 기록 (logs/daily_log.json)
5) 텔레그램 알림 발송

⚠️ 실거래 투입 전 체크리스트
-----------------------------
[ ] .env의 KIS_IS_PAPER=true 로 모의투자 먼저 검증
[ ] kis_client.py의 TR_ID들을 KIS Developers 공식 문서와 대조
[ ] get_overseas_balance()의 응답 필드명이 실제 응답과 일치하는지 1회 수동 확인
[ ] 최초 1회는 state.json을 지운 상태(신규 사이클)로 실행해 그리드가 합리적으로 나오는지 확인
"""

import os
import sys
import time
import traceback
from datetime import date

import rebalance_engine as engine
import state_manager as sm
import kis_client as kis
import daily_logger as logger
import notifier

SYMBOL = "TQQQ"
BIWEEKLY_DEPOSIT_USD = float(os.getenv("BIWEEKLY_DEPOSIT_USD", "0"))


def _place_grid_orders(sell_grid_remaining: list, buy_grid_remaining: list) -> int:
    """잔여 그리드를 오늘자로 전량 지정가 주문 전송. 성공 건수 반환.
    KIS API는 초당 요청 수 제한(TPS)이 있어 각 주문 사이에 짧은 딜레이를 둔다."""
    placed = 0
    for leg in sell_grid_remaining:
        result = kis.place_limit_order(SYMBOL, "sell", qty=1, price=leg["price"])
        if result["success"]:
            placed += 1
        else:
            print(f"  [매도 주문 실패] price={leg['price']:.2f} msg={result['message']}")
        time.sleep(1.0)

    for leg in buy_grid_remaining:
        result = kis.place_limit_order(SYMBOL, "buy", qty=1, price=leg["price"])
        if result["success"]:
            placed += 1
        else:
            print(f"  [매수 주문 실패] price={leg['price']:.2f} msg={result['message']}")
        time.sleep(1.0)

    return placed


def _start_new_cycle(state: dict, qty: int, pool: float, current_price: float) -> dict:
    """사이클 시작(Day1) 또는 최초 실행: V/밴드/그리드 재계산 후 전량 주문."""
    v_old = state.get("v_current") or 0.0

    if not state.get("initialized"):
        # 최초 실행: V_old를 알 수 없으므로 "현재 보유주식 평가금액"을 V_old로 가정한다.
        # 이 가정이 마음에 들지 않으면 state.json을 직접 만들어 v_current를 지정한 뒤 실행하세요.
        v_old = qty * current_price
        print(f"  [최초 실행] v_old를 현재 평가금액으로 초기화: ${v_old:,.2f}")

    deposit = BIWEEKLY_DEPOSIT_USD
    result = engine.run_cycle_calculation(
        v_old=v_old,
        pool=pool,
        deposit=deposit,
        current_qty=qty,
    )

    # 기존 미체결 주문 정리 (혹시 남아있다면)
    cancelled = kis.cancel_all_pending_orders(SYMBOL)
    if cancelled:
        print(f"  기존 미체결 주문 {cancelled}건 취소")
    time.sleep(1.0)

    placed = _place_grid_orders(
        [o.to_dict() for o in result.sell_grid],
        [o.to_dict() for o in result.buy_grid],
    )

    state = sm.start_new_cycle(
        state,
        v_new=result.v_new,
        buy_line=result.buy_line,
        sell_line=result.sell_line,
        pool_buy_limit=result.pool_buy_limit,
    )
    state["sell_grid_remaining"] = [o.to_dict() for o in result.sell_grid]
    state["buy_grid_remaining"] = [o.to_dict() for o in result.buy_grid]
    state["qty_at_cycle_start"] = qty

    return state, placed


def _continue_cycle(state: dict, qty: int) -> tuple:
    """사이클 중간(Day 2~10): 전일 대비 체결 추정 후 잔여 그리드 재주문."""
    qty_at_cycle_start = state.get("qty_at_cycle_start", qty)
    net_change = qty - qty_at_cycle_start  # 양수: 순매수 체결, 음수: 순매도 체결

    sell_remaining = state.get("sell_grid_remaining", [])
    buy_remaining = state.get("buy_grid_remaining", [])

    if net_change > 0:
        # 매수 체결 추정 -> buy_grid에서 시장가에 가장 가까운(=가격이 가장 높은) 것부터 제거
        buy_remaining = sorted(buy_remaining, key=lambda x: -x["price"])
        buy_remaining = buy_remaining[net_change:]
    elif net_change < 0:
        # 매도 체결 추정 -> sell_grid에서 시장가에 가장 가까운(=가격이 가장 낮은) 것부터 제거
        sell_count = -net_change
        sell_remaining = sorted(sell_remaining, key=lambda x: x["price"])
        sell_remaining = sell_remaining[sell_count:]

    # 오늘자 기준 수량 재동기화 (다음날 비교 기준점 갱신)
    state["qty_at_cycle_start"] = qty
    state["sell_grid_remaining"] = sell_remaining
    state["buy_grid_remaining"] = buy_remaining

    kis.cancel_all_pending_orders(SYMBOL)  # 안전장치 (보통 자동취소되어 이미 비어있음)
    time.sleep(1.0)
    placed = _place_grid_orders(sell_remaining, buy_remaining)

    state = sm.advance_day(state)
    return state, placed


def run_daily() -> None:
    state = sm.load_state()

    if sm.is_already_run_today(state):
        print(f"[{date.today()}] 오늘 이미 실행되었습니다. 종료합니다.")
        return

    balance = kis.get_overseas_balance()
    qty = balance["qty"]
    pool = balance["cash_balance"]
    
    if qty == 0 and pool <= 0.0:
        print("[경고] TQQQ 보유 수량과 예수금이 모두 0입니다. 전략을 시작할 수 없습니다. 계좌에 예수금을 입금하거나 TQQQ를 수동으로 매수한 뒤 실행해주세요.")
        notifier.send_message("[경고] TQQQ 보유 수량과 예수금이 모두 0입니다. 자동매매를 시작할 수 없습니다.")
        return

    time.sleep(1.0)  # KIS API 초당 요청 제한(TPS) 회피
    current_price = kis.get_current_price(SYMBOL)

    is_cycle_start = (not state.get("initialized")) or sm.is_cycle_end(state)

    if is_cycle_start:
        print(f"[{date.today()}] 사이클 시작(Day 1) - V/밴드/그리드 재계산")
        state, placed = _start_new_cycle(state, qty, pool, current_price)
        note = f"신규 사이클 {state['cycle_number']} 시작"
    else:
        print(f"[{date.today()}] 사이클 진행 중 (Day {state['day_in_cycle'] + 1}/10)")
        state, placed = _continue_cycle(state, qty)
        note = ""

    state = sm.mark_run_today(state)
    sm.save_state(state)

    eval_amount = qty * current_price + pool
    entry = logger.append_daily_entry(
        cycle_number=state["cycle_number"],
        day_in_cycle=state["day_in_cycle"],
        eval_amount=eval_amount,
        v_current=state["v_current"],
        v_min=state["buy_line"],
        v_max=state["sell_line"],
        pool=pool,
        holdings_qty=qty,
        current_price=current_price,
        orders_placed_today=placed,
        note=note,
    )

    notifier.send_message(notifier.format_daily_report(entry))
    print("일일 실행 완료.")


if __name__ == "__main__":
    try:
        run_daily()
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr)
        try:
            notifier.send_message(notifier.format_error_alert(str(e)))
        except Exception:
            pass
        sys.exit(1)
