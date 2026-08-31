"""CSRF / 登录限速。"""

from __future__ import annotations

from app.security import (
    login_rate_allow,
    login_rate_clear,
    login_rate_fail,
)


def test_login_rate_limit():
    ip = "203.0.113.9"
    login_rate_clear(ip)
    for _ in range(5):
        assert login_rate_allow(ip)
        login_rate_fail(ip)
    assert not login_rate_allow(ip)
    login_rate_clear(ip)
    assert login_rate_allow(ip)
