"""FastAPI 依赖。"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models import User
from app.repositories import user_repo


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return user_repo.get_by_id(db, int(user_id))


class LoginRequired(Exception):
    def __init__(self, next_path: str) -> None:
        self.next_path = next_path


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user = get_current_user_optional(request, db)
    if not user:
        raise LoginRequired(request.url.path)
    return user


def require_user(request: Request, db: Session) -> User | RedirectResponse:
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(
            url=f"/login?next={request.url.path}", status_code=303
        )
    return user


def session_db() -> Generator[Session, None, None]:
    """BackgroundTasks / cron 用独立 Session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
