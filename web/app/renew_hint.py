"""续签窗口提示（与 acme.sh --cron / renew_days 一致）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RenewHint:
    in_window: bool
    level: str  # expired | due | wait | unavailable
    message: str
    days_until_window: int | None
    renew_days: int
    days_left: int | None


def clamp_renew_days(renew_days: int) -> int:
    return max(7, min(60, renew_days))


def days_until_expiry(expires_at: datetime, now: datetime) -> int:
    return int((expires_at - now).total_seconds() // 86400)


def renew_hint(
    *,
    expires_at: datetime | None,
    renew_days: int,
    now: datetime,
    enabled: bool = True,
    verification_status: str = "verified",
) -> RenewHint | None:
    if not enabled:
        return None
    if verification_status == "lost":
        return RenewHint(
            in_window=False,
            level="unavailable",
            message="归属已失效，续签已暂停",
            days_until_window=None,
            renew_days=clamp_renew_days(renew_days),
            days_left=None,
        )
    if verification_status != "verified":
        return None
    rd = clamp_renew_days(renew_days)
    if not expires_at:
        return RenewHint(
            in_window=False,
            level="unavailable",
            message="尚未签发，无法续签",
            days_until_window=None,
            renew_days=rd,
            days_left=None,
        )

    left = days_until_expiry(expires_at, now)
    if left < 0:
        return RenewHint(
            in_window=True,
            level="expired",
            message=f"已过期 {-left} 天，请立即续签",
            days_until_window=0,
            renew_days=rd,
            days_left=left,
        )
    if left <= rd:
        return RenewHint(
            in_window=True,
            level="due",
            message=f"已进入续签窗口（到期前 {rd} 天），续签会换新证",
            days_until_window=0,
            renew_days=rd,
            days_left=left,
        )
    until = left - rd
    return RenewHint(
        in_window=False,
        level="wait",
        message=f"距续签窗口还有 {until} 天（到期前 {rd} 天），现在续签不会换证",
        days_until_window=until,
        renew_days=rd,
        days_left=left,
    )


def job_was_no_renewal(log_tail: str | None) -> bool:
    if not log_tail:
        return False
    return "no renewal needed" in log_tail.lower()
