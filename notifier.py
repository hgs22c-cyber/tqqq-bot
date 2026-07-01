# -*- coding: utf-8 -*-
"""
Telegram 알림 모듈
==================
카카오톡/Line/Discord/Slack 중에서 **Telegram을 추천**하는 이유:
  - 봇 생성이 가장 간단함 (BotFather와 대화 몇 번이면 끝, 별도 심사 없음)
  - 무료, 서버 화이트리스트/방화벽 이슈 거의 없음
  - Discord/Slack처럼 워크스페이스/서버를 새로 만들 필요 없이 개인 채팅으로 바로 수신
  - 카카오톡은 개인 알림봇 API가 비즈니스 채널 심사 등 진입장벽이 있고,
    Line도 국내에서 접근성이 떨어짐

다른 채널(Discord/Slack)로 바꾸고 싶다면 send_message() 내부의 requests.post 부분만
Webhook URL 방식으로 바꾸면 되며, 나머지 코드는 그대로 재사용 가능합니다.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_message(text: str) -> bool:
    """텔레그램으로 메시지 전송. 실패해도 예외를 던지지 않고 False 반환(매매 흐름을 막지 않기 위함)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[알림 미설정] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID가 .env에 없습니다.")
        print(f"[알림 내용]\n{text}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        res = requests.post(url, data=payload, timeout=10)
        res.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[알림 전송 실패] {e}")
        print(f"[알림 내용]\n{text}")
        return False


def format_daily_report(entry: dict) -> str:
    """daily_logger의 entry(dict)를 텔레그램 메시지 형태로 변환."""
    return (
        f"*TQQQ 리밸런싱 봇 - 일일 리포트*\n"
        f"📅 {entry['date']}  (사이클 {entry['cycle_number']} / Day {entry['day_in_cycle']}/10)\n\n"
        f"💰 평가금: ${entry['eval_amount']:,.2f}\n"
        f"🎯 V(목표): ${entry['v_current']:,.2f}\n"
        f"📉 V_min(BuyLine): ${entry['v_min']:,.2f}\n"
        f"📈 V_max(SellLine): ${entry['v_max']:,.2f}\n"
        f"💵 Pool(예수금): ${entry['pool']:,.2f}\n"
        f"📦 보유수량: {entry['holdings_qty']}주\n"
        f"💲 현재가: ${entry['current_price']:,.2f}\n"
        f"📝 오늘 신규 주문: {entry['orders_placed_today']}건\n"
        + (f"\nℹ️ {entry['note']}" if entry.get("note") else "")
    )


def format_error_alert(message: str) -> str:
    return f"🚨 *TQQQ 봇 오류 발생*\n\n```\n{message}\n```\n서버 로그를 확인해주세요."
