"""续签在归属丢失时跳过。"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import register_user
from app.cert_service import CertService
from app.database import Base
from app.schemas import CertCreateForm
from app.settings import Settings
from tests.helpers import seed_ali_qiniu_profile


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="sqlite://",
        secret_key="s" * 32,
        web_master_key=base64.b64encode(os.urandom(32)).decode(),
        project_root=tmp_path,
        web_data_root=tmp_path / "webdata",
        acme_ca="letsencrypt_test",
        default_renew_days=15,
        session_max_age=3600,
        log_level="INFO",
        stale_job_minutes=15,
        notify_webhook="",
        notify_provider="dingtalk",
    )


def test_renew_skips_when_ownership_lost(db, settings):
    user = register_user(db, "r@example.com", "password123")
    profile = seed_ali_qiniu_profile(db, user.id, settings)
    svc = CertService(db, settings)
    cert = svc.create_certificate(
        user.id,
        CertCreateForm(
            name="c1",
            acme_email="ops@example.com",
            profile_id=profile.id,
            issue_domains=["example.com", "*.example.com"],
            deploy_targets=[
                {"type": "qiniu_cdn", "domains": ["cdn.example.com"], "https": {}}
            ],
        ),
    )
    cert.verification_status = "verified"
    cert.verified_at = cert.created_at
    cert.status = "active"
    cert.enabled = True
    db.commit()

    with patch("app.ownership_service.query_txt", return_value=[]):
        svc.renew_certificate(cert.id)

    db.refresh(cert)
    assert cert.verification_status == "lost"
    assert cert.last_error and "ownership" in cert.last_error.lower()
    assert cert.status == "active"
