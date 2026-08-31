"""注册 / 登录 / 密码哈希。"""

from __future__ import annotations

import bcrypt
from sqlalchemy.orm import Session

from app.models import User
from app.repositories import user_repo


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "ascii"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("ascii")
        )
    except ValueError:
        return False


def register_user(db: Session, email: str, password: str) -> User:
    email = email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise ValueError("invalid email")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if user_repo.get_by_email(db, email):
        raise ValueError("email already registered")
    user = User(email=email, password_hash=hash_password(password))
    return user_repo.create(db, user)


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = user_repo.get_by_email(db, email.strip().lower())
    if not user or not verify_password(password, user.password_hash):
        return None
    return user
