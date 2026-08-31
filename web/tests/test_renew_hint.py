"""续签窗口提示。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.renew_hint import job_was_no_renewal, renew_hint


def _dt(days_from_now: int) -> datetime:
    base = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    return base + timedelta(days=days_from_now)


def test_renew_hint_in_window():
    now = _dt(0)
    hint = renew_hint(expires_at=_dt(10), renew_days=15, now=now)
    assert hint is not None
    assert hint.in_window is True
    assert hint.level == "due"


def test_renew_hint_not_yet():
    now = _dt(0)
    hint = renew_hint(expires_at=_dt(79), renew_days=15, now=now)
    assert hint is not None
    assert hint.in_window is False
    assert hint.level == "wait"
    assert hint.days_until_window == 64


def test_renew_hint_expired():
    now = _dt(0)
    hint = renew_hint(expires_at=_dt(-3), renew_days=15, now=now)
    assert hint is not None
    assert hint.in_window is True
    assert hint.level == "expired"


def test_job_was_no_renewal():
    assert job_was_no_renewal("acme cron ok (no renewal needed)")
    assert not job_was_no_renewal("deploy ok")
