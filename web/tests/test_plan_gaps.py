"""负向与改绑相关单测。"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import register_user
from app.cert_service import CertService
from app.compat import assert_dns_compatible
from app.credential_service import (
    create_credential,
    create_profile,
    delete_credential,
    delete_profile,
    update_credential,
)
from app.database import Base
from app.schemas import CertCreateForm, CertUpdateForm
from app.settings import Settings
from tests.helpers import seed_ali_qiniu_profile
from qiniu_cert.acme_plan import deploy_hook_for
from qiniu_cert.config import CertificateConfig, TargetAliyunClb


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path}/neg.db")
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


def test_incompatible_dns_matrix():
    with pytest.raises(ValueError, match="只能引用"):
        assert_dns_compatible("dns_ali", "qiniu")


def test_delete_credential_in_use(db, settings):
    user = register_user(db, "d@example.com", "password123")
    profile = seed_ali_qiniu_profile(db, user.id, settings)
    with pytest.raises(ValueError, match="仍被配置档引用"):
        delete_credential(db, user.id, profile.dns_credential_id)


def test_delete_profile_in_use(db, settings):
    user = register_user(db, "p@example.com", "password123")
    profile = seed_ali_qiniu_profile(db, user.id, settings)
    CertService(db, settings).create_certificate(
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
    with pytest.raises(ValueError, match="仍被证书引用"):
        delete_profile(db, user.id, profile.id)


def test_update_cert_primary_resets_ownership(db, settings):
    user = register_user(db, "u@example.com", "password123")
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
    cert.status = "active"
    db.commit()
    old_token = cert.verification_token

    updated = svc.update_certificate(
        cert.id,
        user.id,
        CertUpdateForm(
            name="c1",
            acme_email="ops@example.com",
            profile_id=profile.id,
            issue_domains=["other.com", "*.other.com"],
            deploy_targets=[
                {"type": "qiniu_cdn", "domains": ["cdn.other.com"], "https": {}}
            ],
            renew_days=15,
        ),
    )
    assert updated.verification_status == "unverified"
    assert updated.verification_token != old_token
    assert updated.primary_domain == "other.com"
    assert updated.status == "pending_verification"


def test_update_credential_rotate(db, settings):
    user = register_user(db, "r@example.com", "password123")
    cred = create_credential(
        db,
        user.id,
        name="qn",
        provider="qiniu",
        access_key="oldak",
        secret_key="oldsk",
        settings=settings,
    )
    update_credential(
        db,
        user.id,
        cred.id,
        access_key="newak",
        secret_key="newsk",
        settings=settings,
    )
    from app.crypto import decrypt, master_key_bytes
    import json

    payload = json.loads(
        decrypt(cred.secret_enc, master_key_bytes(settings.web_master_key))
    )
    assert payload["access_key"] == "newak"


def test_aliyun_shared_dns_and_clb(db, settings):
    user = register_user(db, "a@example.com", "password123")
    ali = create_credential(
        db,
        user.id,
        name="ali",
        provider="aliyun",
        access_key="A",
        secret_key="S",
        settings=settings,
    )
    qn = create_credential(
        db,
        user.id,
        name="qn",
        provider="qiniu",
        access_key="Q",
        secret_key="K",
        settings=settings,
    )
    create_profile(
        db,
        user.id,
        name="cdn",
        dns_provider="dns_ali",
        dns_credential_id=ali.id,
        deploy_type="qiniu_cdn",
        deploy_credential_id=qn.id,
    )
    create_profile(
        db,
        user.id,
        name="clb",
        dns_provider="dns_ali",
        dns_credential_id=ali.id,
        deploy_type="aliyun_clb",
        deploy_credential_id=ali.id,
    )
    # same ali id used twice — no error
    assert ali.id > 0


def test_clb_deploy_hook():
    cert = CertificateConfig(
        name="w",
        issue_domains=["example.com", "*.example.com"],
        dns_provider="dns_ali",
        key_type="rsa-2048",
        targets=[
            TargetAliyunClb(
                region_id="cn-beijing",
                load_balancer_id="lb-1",
                listener_port=443,
            )
        ],
    )
    assert deploy_hook_for(cert) == "clb_wrapper"
