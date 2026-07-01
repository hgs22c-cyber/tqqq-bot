# -*- coding: utf-8 -*-
"""
사이클 상태 관리
================
크론잡이 하루 1번 실행되므로, "지금이 몇 번째 사이클의 몇 번째 거래일인지"를
파일로 영속화해야 한다. state.json 하나에 모든 상태를 저장한다.

state.json 스키마
------------------
{
  "cycle_number": 1,                # 현재 사이클 번호 (1부터 시작)
  "cycle_start_date": "2026-07-01", # 이번 사이클 첫 거래일
  "day_in_cycle": 1,                # 이번 사이클의 몇 번째 거래일인지 (1~10)
  "v_current": 10000000.0,          # 현재 사이클의 목표 밸류 V
  "buy_line": 8500000.0,
  "sell_line": 11500000.0,
  "pool_buy_limit": 750000.0,       # 이번 사이클 매수 한도(Pool*0.75) - 소진 추적용
  "pool_spent_this_cycle": 0.0,     # 이번 사이클에 실제 매수 체결로 쓴 금액
  "last_run_date": "2026-07-01",    # 마지막 실행 일자 (중복 실행 방지)
  "initialized": true
}
"""

import json
import os
from datetime import date

STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")

DEFAULT_STATE = {
    "cycle_number": 0,
    "cycle_start_date": None,
    "day_in_cycle": 0,
    "v_current": 0.0,
    "buy_line": 0.0,
    "sell_line": 0.0,
    "pool_buy_limit": 0.0,
    "pool_spent_this_cycle": 0.0,
    "last_run_date": None,
    "initialized": False,
}


def load_state() -> dict:
    """state.json을 읽어 반환. 없으면 기본값(초기화 필요 상태) 반환."""
    if not os.path.exists(STATE_PATH):
        return dict(DEFAULT_STATE)
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    """state.json에 저장. 원자적 쓰기를 위해 임시파일 -> rename 방식 사용."""
    tmp_path = STATE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATE_PATH)


def is_already_run_today(state: dict) -> bool:
    """오늘 이미 실행됐는지 확인 (크론 중복 실행 방지)."""
    today_str = date.today().isoformat()
    return state.get("last_run_date") == today_str


def mark_run_today(state: dict) -> dict:
    state["last_run_date"] = date.today().isoformat()
    return state


def start_new_cycle(state: dict, v_new: float, buy_line: float, sell_line: float,
                     pool_buy_limit: float) -> dict:
    """새 사이클 시작 시 상태를 초기화한다 (Day 1)."""
    state["cycle_number"] = state.get("cycle_number", 0) + 1
    state["cycle_start_date"] = date.today().isoformat()
    state["day_in_cycle"] = 1
    state["v_current"] = v_new
    state["buy_line"] = buy_line
    state["sell_line"] = sell_line
    state["pool_buy_limit"] = pool_buy_limit
    state["pool_spent_this_cycle"] = 0.0
    state["initialized"] = True
    return state


def advance_day(state: dict) -> dict:
    """같은 사이클 내에서 하루 진행."""
    state["day_in_cycle"] = state.get("day_in_cycle", 0) + 1
    return state


def is_cycle_end(state: dict, cycle_trading_days: int = 10) -> bool:
    """오늘이 사이클의 마지막 거래일인지 (정산 후 재계산 필요 여부)."""
    return state.get("day_in_cycle", 0) >= cycle_trading_days
