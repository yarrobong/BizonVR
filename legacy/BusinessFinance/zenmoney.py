"""Интеграция с API Дзен-мани: OAuth 2.0 и хранение токенов.

Этот модуль реализует стандартный OAuth 2.0 Authorization Code flow,
который требует Дзен-мани:

1. Перенаправляем пользователя на https://api.zenmoney.ru/oauth2/authorize/
   с параметрами response_type=code, client_id и redirect_uri.
2. Пользователь подтверждает доступ, Дзен-мани делает redirect на redirect_uri
   с параметрами ?code=...&state=....
3. Обмениваем code на access_token/refresh_token POST-запросом на
   https://api.zenmoney.ru/oauth2/token/ (grant_type=authorization_code).

Сторона Дзен-мани выступает как OAuth 2.0 Authorization Server / Resource Server,
данное приложение — как OAuth 2.0 Confidential Client.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import requests

from config import (
    ZENMONEY_AUTH_URL,
    ZENMONEY_CLIENT_ID,
    ZENMONEY_CLIENT_SECRET,
    ZENMONEY_REDIRECT_URI,
    ZENMONEY_TOKEN_URL,
)
from db import run_query, run_query_one


def is_zenmoney_configured() -> bool:
    """Проверяем, заполнены ли все необходимые переменные для OAuth 2.0."""
    return bool(ZENMONEY_CLIENT_ID and ZENMONEY_CLIENT_SECRET and ZENMONEY_REDIRECT_URI)


def get_authorization_url(state: str) -> str:
    """Сформировать URL авторизации Дзен-мани согласно OAuth 2.0 Authorization Code flow."""
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": ZENMONEY_CLIENT_ID,
        "redirect_uri": ZENMONEY_REDIRECT_URI,
        "state": state,
    }
    return f"{ZENMONEY_AUTH_URL}?{urlencode(params)}"


def generate_state() -> str:
    """Случайный state для защиты от CSRF (требование OAuth 2.0 best practices)."""
    return secrets.token_urlsafe(32)


def exchange_code_for_token(code: str) -> Dict[str, Any]:
    """Обмен authorization code на access_token и refresh_token.

    Выполняет POST /oauth2/token/ как в документации Дзен-мани:

    grant_type=authorization_code&
    client_id=...&
    client_secret=...&
    code=...&
    redirect_uri=...
    """
    if not is_zenmoney_configured():
        raise RuntimeError("ZenMoney OAuth2 не сконфигурирован (CLIENT_ID/SECRET/REDIRECT_URI).")

    data = {
        "grant_type": "authorization_code",
        "client_id": ZENMONEY_CLIENT_ID,
        "client_secret": ZENMONEY_CLIENT_SECRET,
        "code": code,
        "redirect_uri": ZENMONEY_REDIRECT_URI,
    }
    resp = requests.post(ZENMONEY_TOKEN_URL, data=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


def save_tokens_for_user(user_id: int, token_response: Dict[str, Any]) -> None:
    """Сохранить/обновить токены Дзен-мани для пользователя.

    Ожидаемый формат token_response (по документации):
    {
        "access_token": "...",
        "token_type": "bearer",
        "expires_in": 86400,
        "refresh_token": "..."
    }
    """
    access_token = token_response.get("access_token") or ""
    token_type = token_response.get("token_type") or "bearer"
    refresh_token = token_response.get("refresh_token")

    expires_at: Optional[datetime] = None
    expires_in = token_response.get("expires_in")
    if isinstance(expires_in, (int, float)):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    if not access_token:
        raise ValueError("В ответе /oauth2/token отсутствует access_token.")

    # UPSERT по primary key user_id
    existing = run_query_one(
        "SELECT user_id FROM zenmoney_tokens WHERE user_id = %s",
        (user_id,),
    )
    if existing:
        run_query(
            """
            UPDATE zenmoney_tokens
            SET access_token = %s,
                refresh_token = %s,
                token_type = %s,
                expires_at = %s,
                updated_at = NOW()
            WHERE user_id = %s
            """,
            (access_token, refresh_token, token_type, expires_at, user_id),
        )
    else:
        run_query(
            """
            INSERT INTO zenmoney_tokens (user_id, access_token, refresh_token, token_type, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, access_token, refresh_token, token_type, expires_at),
        )


def get_tokens_for_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Получить сохранённые токены Дзен-мани пользователя (если есть)."""
    row = run_query_one(
        """
        SELECT access_token, refresh_token, token_type, expires_at
        FROM zenmoney_tokens
        WHERE user_id = %s
        """,
        (user_id,),
    )
    if not row:
        return None
    return {
        "access_token": row[0],
        "refresh_token": row[1],
        "token_type": row[2],
        "expires_at": row[3],
    }


def delete_tokens_for_user(user_id: int) -> None:
    """Удалить привязку к Дзен-мани (revoke на стороне сервера Дзен-мани тут не делаем)."""
    run_query("DELETE FROM zenmoney_tokens WHERE user_id = %s", (user_id,))

