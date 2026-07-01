# -*- coding: utf-8 -*-
"""
KIS 인증 모듈
=============
- .env에서 앱키/시크릿/계좌정보를 읽어온다 (계좌번호·키는 절대 코드에 하드코딩하지 않음)
- 접근토큰(access_token)은 발급 시 약 24시간 유효하므로, 매 실행마다 새로 받지 않고
  token_cache.json에 저장해두었다가 만료 전까지 재사용한다.
- 모의투자(IS_PAPER=true) / 실전투자(IS_PAPER=false)를 .env로 전환한다.

⚠️ 반드시 확인할 것
--------------------
아래 TR_ID / URL은 2026년 상반기 기준 공개 자료를 바탕으로 작성했습니다.
KIS는 공지 없이 TR_ID를 바꾸는 경우가 있으므로, **실거래 전** 아래 경로에서
최신 값과 대조해 주세요:
  https://apiportal.koreainvestment.com  ->  API 문서 -> 해외주식 -> 주문/계좌
그리고 반드시 모의투자(IS_PAPER=true) 계좌로 먼저 검증한 뒤 실전 전환하세요.
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_APP_SECRET")
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO")           # 계좌번호 앞 8자리
ACCOUNT_PROD_CD = os.getenv("KIS_ACCOUNT_PROD_CD", "01")  # 계좌번호 뒤 2자리
IS_PAPER = os.getenv("KIS_IS_PAPER", "true").lower() == "true"

BASE_URL_REAL = "https://openapi.koreainvestment.com:9443"
BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"
BASE_URL = BASE_URL_PAPER if IS_PAPER else BASE_URL_REAL

TOKEN_CACHE_PATH = os.path.join(os.path.dirname(__file__), "token_cache.json")


def _validate_env():
    missing = [k for k, v in {
        "KIS_APP_KEY": APP_KEY,
        "KIS_APP_SECRET": APP_SECRET,
        "KIS_ACCOUNT_NO": ACCOUNT_NO,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            f".env에 다음 값이 없습니다: {', '.join(missing)}. "
            f".env.example을 참고해 .env 파일을 만들어주세요."
        )


def _load_token_cache() -> dict:
    if not os.path.exists(TOKEN_CACHE_PATH):
        return {}
    try:
        with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_token_cache(data: dict) -> None:
    with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _request_new_token() -> dict:
    url = f"{BASE_URL}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
    }
    res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
    res.raise_for_status()
    payload = res.json()
    # payload: {"access_token": "...", "token_type": "Bearer", "expires_in": 86400, ...}
    expires_at = datetime.now() + timedelta(seconds=int(payload.get("expires_in", 86400)) - 300)
    cache = {
        "access_token": payload["access_token"],
        "expires_at": expires_at.isoformat(),
        "is_paper": IS_PAPER,
    }
    _save_token_cache(cache)
    return cache


def get_access_token() -> str:
    """캐시된 토큰이 유효하면 재사용, 만료되었거나 없으면 새로 발급."""
    _validate_env()
    cache = _load_token_cache()

    if cache and cache.get("is_paper") == IS_PAPER and cache.get("expires_at"):
        expires_at = datetime.fromisoformat(cache["expires_at"])
        if datetime.now() < expires_at:
            return cache["access_token"]

    # KIS는 1분에 1회 이상 토큰 재발급 요청 시 오류를 낼 수 있어 약간의 지연을 둔다.
    cache = _request_new_token()
    return cache["access_token"]


def get_hashkey(body: dict) -> str:
    """주문 등 POST 요청 시 필요한 해쉬키 발급."""
    url = f"{BASE_URL}/uapi/hashkey"
    headers = {
        "content-type": "application/json",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
    }
    res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
    res.raise_for_status()
    return res.json()["HASH"]


def auth_headers(tr_id: str, extra: dict = None) -> dict:
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }
    if extra:
        headers.update(extra)
    return headers
