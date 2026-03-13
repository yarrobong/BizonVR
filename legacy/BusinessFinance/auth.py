"""Авторизация пользователей и сессии."""
import secrets
from datetime import datetime, timedelta

import bcrypt

from config import SESSION_EXPIRE_DAYS
from db import run_query_one

SESSIONS: dict[str, dict] = {}
SESSION_COOKIE = "bf_session"


def verify_user(username: str, password: str):
    row = run_query_one(
        "SELECT id, username, role, password_hash FROM users WHERE username = %s",
        (username.strip(),),
    )
    if not row:
        return None
    uid, uname, role, pw_hash = row
    pw_bytes = pw_hash.encode() if isinstance(pw_hash, str) else pw_hash
    if not bcrypt.checkpw(password.encode(), pw_bytes):
        return None
    return {"id": uid, "username": uname, "role": role}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def create_session(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(days=SESSION_EXPIRE_DAYS)
    SESSIONS[token] = {"user": user, "expires": expires}
    return token


def get_user_by_token(token: str) -> dict | None:
    if not token:
        return None
    data = SESSIONS.get(token)
    if not data or datetime.utcnow() > data["expires"]:
        if token in SESSIONS:
            del SESSIONS[token]
        return None
    return data["user"]


def destroy_session(token: str) -> None:
    SESSIONS.pop(token, None)
