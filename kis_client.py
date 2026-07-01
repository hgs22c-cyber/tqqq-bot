# -*- coding: utf-8 -*-
"""
KIS 해외주식 API 클라이언트
============================
TQQQ 자동매매에 필요한 최소 기능만 구현:
  1) get_current_price(symbol)      : 현재가 조회
  2) get_overseas_balance()          : 잔고 조회 (보유수량, 예수금/Pool 등)
  3) place_limit_order(...)          : 지정가 매수/매도 주문
  4) get_pending_orders()            : 미체결 주문 조회
  5) cancel_order(...)               : 주문 취소

⚠️ TR_ID 검증 필수
-------------------
아래 TR_ID 상수들은 공개된 커뮤니티 자료를 기반으로 작성되었습니다.
반드시 실거래 전에 KIS Developers 포털(apiportal.koreainvestment.com)의
[API 문서 > 해외주식 > 주문/계좌] 섹션에서 최신 TR_ID를 대조 확인하고,
**모의투자 계좌로 먼저 전체 플로우를 검증**하세요.
"""

import json
import requests
import kis_auth as auth

EXCHANGE_CODE = "NASD"  # TQQQ는 나스닥 상장 -> NASD
CURRENCY = "USD"

# ---------------------------------------------------------------------------
# TR_ID 상수 (실전 / 모의투자) - ⚠️ 위 경고 참고, 실거래 전 최신값 대조 필수
# ---------------------------------------------------------------------------
TR_ID = {
    "buy":            {"real": "TTTT1002U", "paper": "VTTT1002U"},   # 해외주식 매수 주문
    "sell":           {"real": "TTTT1006U", "paper": "VTTT1001U"},   # 해외주식 매도 주문
    "balance":        {"real": "TTTS3012R", "paper": "VTTS3012R"},   # 해외주식 잔고조회
    "price":          {"real": "HHDFS00000300", "paper": "HHDFS00000300"},  # 해외주식 현재가(공통)
    "pending_orders": {"real": "TTTS3018R", "paper": "VTTS3018R"},   # 해외주식 미체결내역조회
    "cancel":         {"real": "TTTT1004U", "paper": "VTTT1004U"},   # 해외주식 정정취소주문
}


def _tr(name: str) -> str:
    return TR_ID[name]["paper" if auth.IS_PAPER else "real"]


def get_current_price(symbol: str) -> float:
    """해외주식 현재가 조회. 실패 시 예외 발생."""
    url = f"{auth.BASE_URL}/uapi/overseas-price/v1/quotations/price"
    headers = auth.auth_headers(_tr("price"))
    params = {
        "AUTH": "",
        "EXCD": "NAS",  # 시세조회 API는 3자리 코드(NAS) 사용. 주문/잔고 API는 4자리(NASD) 사용 - 서로 다름 주의
        "SYMB": symbol,
    }
    res = requests.get(url, headers=headers, params=params, timeout=10)
    if res.status_code != 200:
        print(f"[디버그 get_current_price] status={res.status_code} body={res.text}")
    res.raise_for_status()
    body = res.json()
    if body.get("rt_cd") != "0":
        raise RuntimeError(f"현재가 조회 실패: {body.get('msg1')}")
    output = body.get("output", {})
    print(f"[디버그 get_current_price] raw output={output}")
    price = float(output.get("last") or 0)
    if price <= 0:
        raise RuntimeError(f"현재가가 0 이하로 조회됨 (output={output}) - 필드명이 잘못됐을 수 있음")
    return price


def get_overseas_balance() -> dict:
    """
    해외주식 잔고 조회.
    반환: {
        "qty": 보유수량(int),
        "avg_price": 평균단가(float),
        "eval_amount": 평가금액(float, USD),
        "cash_balance": 외화예수금/Pool(float, USD),
    }
    """
    url = f"{auth.BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance"
    headers = auth.auth_headers(_tr("balance"))
    params = {
        "CANO": auth.ACCOUNT_NO,
        "ACNT_PRDT_CD": auth.ACCOUNT_PROD_CD,
        "OVRS_EXCG_CD": EXCHANGE_CODE,
        "TR_CRCY_CD": CURRENCY,
        "CTX_AREA_FK200": "",
        "CTX_AREA_NK200": "",
    }
    res = requests.get(url, headers=headers, params=params, timeout=10)
    res.raise_for_status()
    body = res.json()
    if body.get("rt_cd") != "0":
        raise RuntimeError(f"잔고 조회 실패: {body.get('msg1')}")

    holdings = body.get("output1", [])
    qty = 0
    avg_price = 0.0
    eval_amount = 0.0
    for h in holdings:
        if h.get("ovrs_pdno") == "TQQQ" or h.get("pdno") == "TQQQ":
            qty = int(float(h.get("ovrs_cblc_qty", 0)))
            avg_price = float(h.get("pchs_avg_pric", 0))
            eval_amount = float(h.get("ovrs_stck_evlu_amt", 0))
            break

    summary = body.get("output2", {})
    # 필드명은 실제 응답 구조에 맞춰 조정 필요 (모의투자로 1회 호출해 실제 키를 확인할 것)
    cash_balance = float(summary.get("frcr_dncl_amt_2", summary.get("frcr_evlu_tota_amt", 0)))

    return {
        "qty": qty,
        "avg_price": avg_price,
        "eval_amount": eval_amount,
        "cash_balance": cash_balance,
    }


def place_limit_order(symbol: str, side: str, qty: int, price: float) -> dict:
    """
    지정가 매수/매도 주문.
    side: "buy" | "sell"
    반환: {"success": bool, "order_no": str|None, "message": str}
    """
    if side not in ("buy", "sell"):
        raise ValueError("side는 'buy' 또는 'sell'이어야 합니다.")
    if qty <= 0:
        raise ValueError("qty는 1 이상이어야 합니다.")

    url = f"{auth.BASE_URL}/uapi/overseas-stock/v1/trading/order"
    body = {
        "CANO": auth.ACCOUNT_NO,
        "ACNT_PRDT_CD": auth.ACCOUNT_PROD_CD,
        "OVRS_EXCG_CD": EXCHANGE_CODE,
        "PDNO": symbol,
        "ORD_QTY": str(qty),
        "OVRS_ORD_UNPR": f"{price:.2f}",
        "ORD_SVR_DVSN_CD": "0",
        "ORD_DVSN": "00",  # 00: 지정가
    }
    hashkey = auth.get_hashkey(body)
    headers = auth.auth_headers(_tr(side), extra={"hashkey": hashkey})

    res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
    res.raise_for_status()
    resp = res.json()

    success = resp.get("rt_cd") == "0"
    order_no = resp.get("output", {}).get("ODNO") if success else None
    return {"success": success, "order_no": order_no, "message": resp.get("msg1", "")}


def get_pending_orders() -> list:
    """미체결 주문 목록 조회. 각 원소: {"order_no", "symbol", "side", "qty", "price"}"""
    url = f"{auth.BASE_URL}/uapi/overseas-stock/v1/trading/inquire-nccs"
    headers = auth.auth_headers(_tr("pending_orders"))
    params = {
        "CANO": auth.ACCOUNT_NO,
        "ACNT_PRDT_CD": auth.ACCOUNT_PROD_CD,
        "OVRS_EXCG_CD": EXCHANGE_CODE,
        "SORT_SQN": "DS",
        "CTX_AREA_FK200": "",
        "CTX_AREA_NK200": "",
    }
    res = requests.get(url, headers=headers, params=params, timeout=10)
    res.raise_for_status()
    body = res.json()
    if body.get("rt_cd") != "0":
        raise RuntimeError(f"미체결 조회 실패: {body.get('msg1')}")

    result = []
    for o in body.get("output", []):
        result.append({
            "order_no": o.get("odno"),
            "symbol": o.get("pdno"),
            "side": "buy" if o.get("sll_buy_dvsn_cd") == "02" else "sell",
            "qty": int(float(o.get("nccs_qty", 0))),
            "price": float(o.get("ft_ord_unpr3", 0)),
        })
    return result


def cancel_order(order_no: str, symbol: str, qty: int, price: float) -> dict:
    """미체결 주문 취소."""
    url = f"{auth.BASE_URL}/uapi/overseas-stock/v1/trading/order-rvsecncl"
    body = {
        "CANO": auth.ACCOUNT_NO,
        "ACNT_PRDT_CD": auth.ACCOUNT_PROD_CD,
        "OVRS_EXCG_CD": EXCHANGE_CODE,
        "PDNO": symbol,
        "ORGN_ODNO": order_no,
        "RVSE_CNCL_DVSN_CD": "02",  # 02: 취소
        "ORD_QTY": str(qty),
        "OVRS_ORD_UNPR": f"{price:.2f}",
        "ORD_SVR_DVSN_CD": "0",
    }
    hashkey = auth.get_hashkey(body)
    headers = auth.auth_headers(_tr("cancel"), extra={"hashkey": hashkey})

    res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
    res.raise_for_status()
    resp = res.json()
    return {"success": resp.get("rt_cd") == "0", "message": resp.get("msg1", "")}


def cancel_all_pending_orders(symbol: str) -> int:
    """지정 종목의 모든 미체결 주문을 취소. 취소된 건수 반환."""
    pending = get_pending_orders()
    count = 0
    for o in pending:
        if o["symbol"] == symbol:
            result = cancel_order(o["order_no"], o["symbol"], o["qty"], o["price"])
            if result["success"]:
                count += 1
    return count
