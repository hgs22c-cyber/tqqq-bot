# -*- coding: utf-8 -*-
"""
TQQQ 리밸런싱 자동매매 - 핵심 계산 로직
=========================================
전략 문서(1~4장)를 그대로 구현한 순수 계산 함수 모음.
KIS API, 파일 입출력 등 외부 의존성이 전혀 없어 단독으로 테스트 가능하다.

전략 요약
---------
- 사이클: 10거래일(2주)마다 V(목표 밸류)를 재계산
- V_new = V_old + Pool/G + 적립금
- 밴드: BuyLine = V_new * 0.85, SellLine = V_new * 1.15
- 매도망: 최대밴드를 넘지 않도록, 보유수량 1주씩 줄여가며 지정가 계산
- 매수망: 최소밴드 아래로 떨어지지 않도록, 보유수량 1주씩 늘려가며 지정가 계산
          (단, 누적 매수금액이 Pool*0.75 한도를 넘지 않는 선까지)
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 상수 (전략 문서 1장 기준)
# ---------------------------------------------------------------------------
G_GRADIENT = 10          # V값 상승 기울기 조절 상수
BAND_RATIO = 0.15        # 밴드 비율 (±15%)
POOL_USAGE_LIMIT_RATIO = 0.75   # 사이클당 Pool 사용 한도 (75%)
CYCLE_TRADING_DAYS = 10  # 1사이클 = 10거래일(2주)
MAX_GRID_LEGS = 60       # 매수/매도 그리드 최대 건수 (폭주 방지 안전장치)
MIN_ORDER_PRICE = 1.00   # 최소 주문 가격 ($1 미만은 비현실적이므로 차단)


@dataclass
class GridOrder:
    """그리드 상의 개별 지정가 주문 1건 (항상 1주 단위)"""
    price: float
    qty: int = 1

    def to_dict(self):
        return {"price": round(self.price, 2), "qty": self.qty}


@dataclass
class RebalanceResult:
    v_old: float
    pool_before: float
    deposit: float
    v_new: float
    buy_line: float
    sell_line: float
    pool_buy_limit: float          # 이번 사이클 매수에 쓸 수 있는 최대 현금
    sell_grid: list = field(default_factory=list)   # list[GridOrder], 낮은가->높은가 순
    buy_grid: list = field(default_factory=list)    # list[GridOrder], 높은가->낮은가 순
    buy_grid_total_cost: float = 0.0

    def summary_dict(self):
        return {
            "v_old": round(self.v_old, 2),
            "pool_before": round(self.pool_before, 2),
            "deposit": round(self.deposit, 2),
            "v_new": round(self.v_new, 2),
            "buy_line": round(self.buy_line, 2),
            "sell_line": round(self.sell_line, 2),
            "pool_buy_limit": round(self.pool_buy_limit, 2),
            "sell_grid_count": len(self.sell_grid),
            "buy_grid_count": len(self.buy_grid),
            "buy_grid_total_cost": round(self.buy_grid_total_cost, 2),
        }


# ---------------------------------------------------------------------------
# Step 1: 새로운 목표 밸류(V) 계산
# ---------------------------------------------------------------------------
def calculate_new_v(v_old: float, pool: float, deposit: float, g: float = G_GRADIENT) -> float:
    """
    V_new = V_old + Pool/G + 적립금

    v_old   : 이전 사이클의 목표 밸류
    pool    : 현재 계좌에 남은 가용 현금(예수금)
    deposit : 이번 사이클에 신규로 투입하는 적립금 (없으면 0)
    """
    return v_old + (pool / g) + deposit


# ---------------------------------------------------------------------------
# Step 2: 밴드 계산
# ---------------------------------------------------------------------------
def calculate_bands(v_new: float, band_ratio: float = BAND_RATIO) -> tuple:
    """
    Buy Line  = V_new * (1 - band_ratio)   # 기본값: 0.85
    Sell Line = V_new * (1 + band_ratio)   # 기본값: 1.15
    """
    buy_line = v_new * (1 - band_ratio)
    sell_line = v_new * (1 + band_ratio)
    return buy_line, sell_line


# ---------------------------------------------------------------------------
# Step 3-A: 매도망(Sell Grid) 생성
# ---------------------------------------------------------------------------
def generate_sell_grid(sell_line: float, current_qty: int) -> list:
    """
    현재 보유수량을 대상으로, 최대밴드(sell_line)를 넘지 않도록
    1주 단위 지정가 매도 리스트를 생성한다.

    로직 (전략 문서 3장 A):
      temp = current_qty
      while temp > 1:
          price = sell_line / temp
          append(price, qty=1)
          temp -= 1

    결과: 총 (current_qty - 1)건의 매도 주문.
          temp이 작아질수록(=더 많이 팔았다고 가정할수록) price가 높아지므로,
          그리드는 "낮은 가격 -> 높은 가격" 순으로 정렬된다.
          즉 주가가 오를수록 더 높은 값에 매도하는 구조.
    """
    if current_qty <= 1:
        return []

    grid = []
    temp_qty = current_qty
    while temp_qty > 1 and len(grid) < MAX_GRID_LEGS:
        price = sell_line / temp_qty
        grid.append(GridOrder(price=price, qty=1))
        temp_qty -= 1

    # temp_qty가 클 때(초반) 계산된 가격이 더 낮으므로, 리스트를 뒤집어
    # "낮은 가격 -> 높은 가격" 오름차순으로 정렬해서 반환한다.
    grid.reverse()
    return grid


# ---------------------------------------------------------------------------
# Step 3-B: 매수망(Buy Grid) 생성
# ---------------------------------------------------------------------------
def generate_buy_grid(buy_line: float, current_qty: int, pool_buy_limit: float) -> tuple:
    """
    현재 보유수량을 기준으로, 최소밴드(buy_line) 아래로 평가금이 떨어지지 않도록
    1주 단위 지정가 매수 리스트를 생성한다. 단, 누적 매수금액이
    pool_buy_limit(=현재 Pool * 0.75)을 넘지 않는 선까지만 생성한다.

    로직 (전략 문서 3장 B):
      temp = current_qty
      spent = 0
      loop:
          price = buy_line / (temp + 1)
          if spent + price > pool_buy_limit: break   # 한도 초과 시 중단
          append(price, qty=1)
          temp += 1
          spent += price

    결과: temp이 커질수록(=더 많이 샀다고 가정할수록) price가 낮아지므로,
          그리드는 "높은 가격 -> 낮은 가격" 순으로 정렬된다.
          즉 주가가 하락할수록 더 낮은 값에 추가 매수하는 구조 (물타기 방지형 분할매수).

    반환값: (grid_list, total_cost)
    """
    grid = []
    temp_qty = current_qty
    spent = 0.0

    while len(grid) < MAX_GRID_LEGS:
        price = buy_line / (temp_qty + 1)
        # 안전장치 1: 누적 매수금액이 한도 초과 시 중단
        if spent + price > pool_buy_limit:
            break
        # 안전장치 2: 비현실적으로 낮은 가격의 주문은 생성하지 않음
        if price < MIN_ORDER_PRICE:
            break
        grid.append(GridOrder(price=price, qty=1))
        spent += price
        temp_qty += 1

    return grid, spent


# ---------------------------------------------------------------------------
# 전체 사이클 재계산 (Step 1~3 통합)
# ---------------------------------------------------------------------------
def run_cycle_calculation(
    v_old: float,
    pool: float,
    deposit: float,
    current_qty: int,
    g: float = G_GRADIENT,
    band_ratio: float = BAND_RATIO,
    pool_usage_limit_ratio: float = POOL_USAGE_LIMIT_RATIO,
) -> RebalanceResult:
    """사이클 전환 시점에 호출되는 통합 함수. Step 1~3을 순서대로 수행한다."""
    v_new = calculate_new_v(v_old, pool, deposit, g)
    buy_line, sell_line = calculate_bands(v_new, band_ratio)

    pool_buy_limit = pool * pool_usage_limit_ratio

    sell_grid = generate_sell_grid(sell_line, current_qty)
    buy_grid, buy_grid_total_cost = generate_buy_grid(buy_line, current_qty, pool_buy_limit)

    return RebalanceResult(
        v_old=v_old,
        pool_before=pool,
        deposit=deposit,
        v_new=v_new,
        buy_line=buy_line,
        sell_line=sell_line,
        pool_buy_limit=pool_buy_limit,
        sell_grid=sell_grid,
        buy_grid=buy_grid,
        buy_grid_total_cost=buy_grid_total_cost,
    )


# ---------------------------------------------------------------------------
# 간단한 자체 테스트 (python rebalance_engine.py 로 직접 실행 가능)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 예시: V_old=10,000,000원 상당, Pool=1,000,000, 적립금=500,000, 보유 20주
    result = run_cycle_calculation(
        v_old=10_000_000,
        pool=1_000_000,
        deposit=500_000,
        current_qty=20,
    )

    print("=== Step 1~2: V / 밴드 ===")
    for k, v in result.summary_dict().items():
        print(f"  {k}: {v}")

    print("\n=== 매도망 (낮은가 -> 높은가) ===")
    for o in result.sell_grid:
        print(f"  {o.qty}주 @ {o.price:,.2f}")

    print("\n=== 매수망 (높은가 -> 낮은가) ===")
    for o in result.buy_grid:
        print(f"  {o.qty}주 @ {o.price:,.2f}")
