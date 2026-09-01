"""手动同步部署 / 立即续签。"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import register_user
from app.cert_service import CertService, OwnershipError
from app.database import Base
from app.repositories import cert_repo
from app.schemas import CertCreateForm
from app.settings import Settings
from qiniu_cert.acme_plan import acme_cert_dir
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


def _active_cert(db, settings, *, with_pem: bool = True):
    user = register_user(db, "manual@example.com", "password123")
    profile = seed_ali_qiniu_profile(db, user.id, settings)
    svc = CertService(db, settings)
    cert = svc.create_certificate(
        user.id,
        CertCreateForm(
            name="manual",
            acme_email="ops@example.com",
            profile_id=profile.id,
            issue_domains=["example.com", "cdn.example.com"],
            deploy_targets=[
                {"type": "qiniu_cdn", "domains": ["cdn.example.com"], "https": {}}
            ],
        ),
    )
    cert.verification_status = "verified"
    cert.verified_at = cert.created_at
    cert.status = "active"
    cert.enabled = True
    cert.expires_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(cert)

    if with_pem:
        acme_home = Path(cert.acme_home)
        cert_dir = acme_home / acme_cert_dir(cert.primary_domain, cert.key_type)
        cert_dir.mkdir(parents=True, exist_ok=True)
        (cert_dir / f"{cert.primary_domain}.key").write_text("fake-key", encoding="utf-8")
        (cert_dir / "fullchain.cer").write_text("fake-chain", encoding="utf-8")
    return user, cert, svc


def test_deploy_now_rejects_unverified(db, settings):
    user, cert, svc = _active_cert(db, settings)
    cert.verification_status = "unverified"
    db.commit()
    with pytest.raises(OwnershipError):
        svc.deploy_now(cert.id, user.id)


def test_deploy_now_rejects_missing_pem(db, settings):
    user, cert, svc = _active_cert(db, settings, with_pem=False)
    with pytest.raises(ValueError, match="certificate files not found"):
        svc.deploy_now(cert.id, user.id)


def test_deploy_now_rejects_busy(db, settings):
    user, cert, svc = _active_cert(db, settings)
    cert.status = "deploying"
    db.commit()
    with pytest.raises(ValueError, match="job already running"):
        svc.deploy_now(cert.id, user.id)


def test_deploy_now_marks_deploying(db, settings):
    user, cert, svc = _active_cert(db, settings)
    out = svc.deploy_now(cert.id, user.id)
    assert out.status == "deploying"
    job = cert_repo.latest_job(db, cert.id)
    assert job and job.job_type == "deploy" and job.status == "running"


def test_renew_now_marks_renewing(db, settings):
    user, cert, svc = _active_cert(db, settings)
    out = svc.renew_now(cert.id, user.id)
    assert out.status == "renewing"
    job = cert_repo.latest_job(db, cert.id)
    assert job and job.job_type == "renew" and job.status == "running"


def test_renew_now_rejects_busy(db, settings):
    user, cert, svc = _active_cert(db, settings)
    cert.status = "renewing"
    db.commit()
    with pytest.raises(ValueError, match="job already running"):
        svc.renew_now(cert.id, user.id)


def test_deploy_certificate_success(db, settings):
    user, cert, svc = _active_cert(db, settings)
    runtime_env = {
        "QINIU_AK": "ak-test",
        "QINIU_SK": "sk-test",
        "Ali_Key": "ali",
        "Ali_Secret": "secret",
    }

    class FakeRuntime:
        acme_home = Path(cert.acme_home)
        config_path = Path(cert.acme_home).parent / "config.yaml"
        state_path = Path(cert.acme_home).parent / "state" / "state.json"
        env = runtime_env

    FakeRuntime.config_path.write_text("acme:\n  email: ops@example.com\n", encoding="utf-8")
    FakeRuntime.state_path.parent.mkdir(parents=True, exist_ok=True)
    FakeRuntime.state_path.write_text("{}\n", encoding="utf-8")

    with patch.object(svc.builder, "build", return_value=FakeRuntime):
        with patch("app.cert_service.load_config") as load_cfg:
            with patch("app.cert_service.DeployService") as DeploySvc:
                load_cfg.return_value = object()
                DeploySvc.return_value.deploy_from_files.return_value = "cert-123"
                with patch.object(
                    svc.runner,
                    "parse_expires_at",
                    return_value=datetime(2026, 12, 1, tzinfo=timezone.utc).replace(tzinfo=None),
                ):
                    with patch.object(svc.builder, "read_state_to_db", return_value={"cdn.example.com": {}}):
                        svc.deploy_certificate(cert.id)

    db.refresh(cert)
    assert cert.status == "active"
    assert cert.last_error is None
    job = cert_repo.latest_job(db, cert.id)
    assert job is not None
    assert job.job_type == "deploy"
    assert job.status == "success"


def test_renew_now_rejects_unissued(db, settings):
    user, cert, svc = _active_cert(db, settings)
    cert.expires_at = None
    db.commit()
    with pytest.raises(ValueError, match="certificate not issued yet"):
        svc.renew_now(cert.id, user.id)


def test_renew_now_ok(db, settings):
    user, cert, svc = _active_cert(db, settings)
    returned = svc.renew_now(cert.id, user.id)
    assert returned.id == cert.id


def test_list_template_has_manual_buttons():
    template = Path(__file__).resolve().parent.parent / "app/templates/certs/list.html"
    text = template.read_text(encoding="utf-8")
    assert "部署" in text
    assert "续签" in text
    assert "/deploy" in text
    assert "/renew" in text
