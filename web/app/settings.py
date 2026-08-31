"""环境变量 → Settings。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _default_project_root() -> Path:
    # web/app/settings.py → web/ → 仓库根
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    web_master_key: str
    project_root: Path
    web_data_root: Path
    acme_ca: str
    default_renew_days: int
    session_max_age: int
    log_level: str
    stale_job_minutes: int
    notify_webhook: str
    notify_provider: str


@lru_cache
def get_settings() -> Settings:
    project_root = Path(
        os.environ.get("PROJECT_ROOT") or _default_project_root()
    ).resolve()
    web_data = os.environ.get("WEB_DATA_ROOT")
    web_data_root = (
        Path(web_data).resolve()
        if web_data
        else (project_root / ".local" / "web").resolve()
    )
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "mysql+pymysql://qcert:secret@127.0.0.1:3306/qiniu_cert_web?charset=utf8mb4",
        ),
        secret_key=os.environ.get("SECRET_KEY", "dev-insecure-change-me"),
        web_master_key=os.environ.get(
            "WEB_MASTER_KEY",
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        ),
        project_root=project_root,
        web_data_root=web_data_root,
        acme_ca=os.environ.get("ACME_CA", "letsencrypt_test"),
        default_renew_days=int(os.environ.get("DEFAULT_RENEW_DAYS", "15")),
        session_max_age=int(os.environ.get("SESSION_MAX_AGE", str(86400 * 7))),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        stale_job_minutes=int(os.environ.get("STALE_JOB_MINUTES", "15")),
        notify_webhook=os.environ.get("NOTIFY_WEBHOOK", ""),
        notify_provider=os.environ.get("NOTIFY_PROVIDER", "dingtalk"),
    )
