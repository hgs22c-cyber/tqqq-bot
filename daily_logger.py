# -*- coding: utf-8 -*-
"""
Daily Log
=========
매일 실행 후 아래 항목을 하나의 JSON 파일(logs/daily_log.json)에 배열로 누적 기록한다.
  - date, cycle_number, day_in_cycle
  - eval_amount (평가금 = 보유수량*현재가 + 예수금)
  - v_current, v_min(=buy_line), v_max(=sell_line)
  - pool (현재 예수금)
  - holdings_qty, current_price
  - orders_placed_today (오늘 새로 낸 주문 수), orders_filled_since_cycle_start
"""

import json
import os
from datetime import date

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "daily_log.json")


def _load_log() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_log(entries: list) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    tmp_path = LOG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, LOG_PATH)


def append_daily_entry(
    cycle_number: int,
    day_in_cycle: int,
    eval_amount: float,
    v_current: float,
    v_min: float,
    v_max: float,
    pool: float,
    holdings_qty: int,
    current_price: float,
    orders_placed_today: int = 0,
    note: str = "",
) -> dict:
    """오늘 날짜로 로그 항목 1건 추가 (같은 날짜에 재실행되면 덮어씀)."""
    entries = _load_log()
    today_str = date.today().isoformat()

    entry = {
        "date": today_str,
        "cycle_number": cycle_number,
        "day_in_cycle": day_in_cycle,
        "eval_amount": round(eval_amount, 2),
        "v_current": round(v_current, 2),
        "v_min": round(v_min, 2),
        "v_max": round(v_max, 2),
        "pool": round(pool, 2),
        "holdings_qty": holdings_qty,
        "current_price": round(current_price, 2),
        "orders_placed_today": orders_placed_today,
        "note": note,
    }

    # 같은 날짜의 기존 항목이 있으면 교체 (같은 날 중복 실행 대비)
    entries = [e for e in entries if e.get("date") != today_str]
    entries.append(entry)
    entries.sort(key=lambda e: e["date"])

    _save_log(entries)
    return entry


def get_all_entries() -> list:
    return _load_log()
