"""CSRF 与登录限速。"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict
from threading import Lock

from fastapi import Form, HTTPException, Request


class CSRFError(Exception):
    pass


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def validate_csrf(request: Request, csrf_token: str | None) -> None:
    expected = request.session.get("csrf_token")
    if (
        not expected
        or not csrf_token
        or not secrets.compare_digest(str(expected), str(csrf_token))
    ):
        raise CSRFError("invalid csrf token")


async def require_csrf(
    request: Request,
    csrf_token: str = Form(...),
) -> None:
    try:
        validate_csrf(request, csrf_token)
    except CSRFError as exc:
        raise HTTPException(status_code=403, detail="CSRF validation failed") from exc


# --- login rate limit: 5 failures / minute / IP ---
_login_failures: dict[str, list[float]] = defaultdict(list)
_login_lock = Lock()
_LOGIN_LIMIT = 5
_LOGIN_WINDOW_SEC = 60


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def login_rate_allow(ip: str) -> bool:
    now = time.time()
    with _login_lock:
        bucket = [t for t in _login_failures[ip] if now - t < _LOGIN_WINDOW_SEC]
        _login_failures[ip] = bucket
        return len(bucket) < _LOGIN_LIMIT


def login_rate_fail(ip: str) -> None:
    with _login_lock:
        _login_failures[ip].append(time.time())


def login_rate_clear(ip: str) -> None:
    with _login_lock:
        _login_failures.pop(ip, None)
