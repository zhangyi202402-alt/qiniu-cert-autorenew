"""auth / FSM 相关单测（SQLite）。"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password, register_user, verify_password
from app.cert_service import CertService, OwnershipError
from app.database import Base
from app.schemas import CertCreateForm
from app.settings import Settings
from tests.helpers import seed_ali_qiniu_profile


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


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


def test_password_hash():
    h = hash_password("password123")
    assert verify_password("password123", h)
    assert not verify_password("wrong", h)


def test_register_and_quota(db, settings):
    user = register_user(db, "u@example.com", "password123")
    user.max_certificates = 1
    db.commit()
    profile = seed_ali_qiniu_profile(db, user.id, settings)
    svc = CertService(db, settings)
    form = CertCreateForm(
        name="c1",
        acme_email="ops@example.com",
        profile_id=profile.id,
        issue_domains=["example.com", "*.example.com"],
        deploy_targets=[
            {"type": "qiniu_cdn", "domains": ["cdn.example.com"], "https": {}}
        ],
    )
    cert = svc.create_certificate(user.id, form)
    assert cert.verification_status == "unverified"
    assert cert.status == "pending_verification"
    assert "_qcert-verify.example.com" == cert.verification_host
    with pytest.raises(ValueError, match="quota"):
        svc.create_certificate(user.id, form)


def test_issue_requires_verified(db, settings):
    user = register_user(db, "v@example.com", "password123")
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
    with pytest.raises(OwnershipError):
        svc._issue_locked(cert.id, job_type="issue")
