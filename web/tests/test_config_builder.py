"""config_builder / compat 单测。"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import register_user
from app.compat import issue_domains_cover, validate_deploy_targets
from app.config_builder import ConfigBuilder
from app.credential_service import create_credential, create_profile
from app.database import Base
from app.schemas import CertCreateForm
from app.cert_service import CertService
from app.settings import Settings
from tests.helpers import seed_ali_qiniu_profile


def _settings(tmp: Path) -> Settings:
    key = base64.b64encode(os.urandom(32)).decode()
    return Settings(
        database_url="sqlite://",
        secret_key="x" * 32,
        web_master_key=key,
        project_root=tmp,
        web_data_root=tmp / "data",
        acme_ca="letsencrypt_test",
        default_renew_days=15,
        session_max_age=3600,
        log_level="INFO",
        stale_job_minutes=15,
        notify_webhook="",
        notify_provider="dingtalk",
    )


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path}/cb.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_issue_domains_cover():
    assert issue_domains_cover(["example.com", "*.example.com"], "cdn.example.com")
    assert not issue_domains_cover(["*.example.com"], "example.com")
    assert not issue_domains_cover(["*.example.com"], "a.b.example.com")


def test_cdn_must_be_covered():
    with pytest.raises(ValueError, match="未被签发域名覆盖"):
        validate_deploy_targets(
            deploy_type="qiniu_cdn",
            issue_domains=["example.com"],
            deploy_targets=[{"type": "qiniu_cdn", "domains": ["other.com"]}],
        )


def test_build_yaml_and_env(db, tmp_path: Path):
    settings = _settings(tmp_path)
    user = register_user(db, "a@b.com", "password123")
    profile = seed_ali_qiniu_profile(db, user.id, settings)
    svc = CertService(db, settings)
    cert = svc.create_certificate(
        user.id,
        CertCreateForm(
            name="main",
            acme_email="ops@example.com",
            profile_id=profile.id,
            issue_domains=["example.com", "*.example.com"],
            deploy_targets=[
                {"type": "qiniu_cdn", "domains": ["cdn.example.com"], "https": {}}
            ],
        ),
    )
    profile = db.get(type(profile), profile.id)
    runtime = ConfigBuilder().build(cert, settings, db=db, profile=profile)
    raw = yaml.safe_load(runtime.config_path.read_text(encoding="utf-8"))
    assert raw["certificates"][0]["dns_provider"] == "dns_ali"
    assert runtime.env["Ali_Key"] == "AK"
    assert runtime.env["QINIU_AK"] == "QAK"


def test_shared_qiniu_two_certs(db, tmp_path: Path):
    settings = _settings(tmp_path)
    user = register_user(db, "s@b.com", "password123")
    profile = seed_ali_qiniu_profile(db, user.id, settings)
    svc = CertService(db, settings)
    c1 = svc.create_certificate(
        user.id,
        CertCreateForm(
            name="c1",
            acme_email="ops@example.com",
            profile_id=profile.id,
            issue_domains=["a.example.com"],
            deploy_targets=[
                {"type": "qiniu_cdn", "domains": ["a.example.com"], "https": {}}
            ],
        ),
    )
    c2 = svc.create_certificate(
        user.id,
        CertCreateForm(
            name="c2",
            acme_email="ops@example.com",
            profile_id=profile.id,
            issue_domains=["b.example.com"],
            deploy_targets=[
                {"type": "qiniu_cdn", "domains": ["b.example.com"], "https": {}}
            ],
        ),
    )
    assert c1.profile_id == c2.profile_id == profile.id


def test_clb_forces_rsa(db, tmp_path: Path):
    settings = _settings(tmp_path)
    user = register_user(db, "c@b.com", "password123")
    ali = create_credential(
        db,
        user.id,
        name="ali",
        provider="aliyun",
        access_key="A",
        secret_key="S",
        settings=settings,
    )
    profile = create_profile(
        db,
        user.id,
        name="clb",
        dns_provider="dns_ali",
        dns_credential_id=ali.id,
        deploy_type="aliyun_clb",
        deploy_credential_id=ali.id,
    )
    cert = CertService(db, settings).create_certificate(
        user.id,
        CertCreateForm(
            name="w",
            acme_email="ops@example.com",
            profile_id=profile.id,
            issue_domains=["example.com", "*.example.com"],
            deploy_targets=[
                {
                    "type": "aliyun_clb",
                    "region_id": "cn-beijing",
                    "load_balancer_id": "lb-1",
                    "listener_port": 443,
                    "domain_extensions": [],
                    "probe_host": "www.example.com",
                }
            ],
        ),
    )
    assert cert.key_type == "rsa-2048"
    runtime = ConfigBuilder().build(cert, settings, db=db)
    raw = yaml.safe_load(runtime.config_path.read_text(encoding="utf-8"))
    assert raw["certificates"][0]["targets"][0]["type"] == "aliyun_clb"
    assert runtime.env["ALIYUN_AK"] == "A"


def test_config_builder_aliyun_cdn(db, tmp_path: Path):
    settings = _settings(tmp_path)
    user = register_user(db, "cdn@example.com", "password123")
    ali = create_credential(
        db,
        user.id,
        name="ali",
        provider="aliyun",
        access_key="A",
        secret_key="S",
        settings=settings,
    )
    profile = create_profile(
        db,
        user.id,
        name="ali-cdn",
        dns_provider="dns_ali",
        dns_credential_id=ali.id,
        deploy_type="aliyun_cdn",
        deploy_credential_id=ali.id,
    )
    cert = CertService(db, settings).create_certificate(
        user.id,
        CertCreateForm(
            name="w",
            acme_email="ops@example.com",
            profile_id=profile.id,
            issue_domains=["cdn.example.com"],
            deploy_targets=[
                {"type": "aliyun_cdn", "domains": ["cdn.example.com"], "https": {}}
            ],
        ),
    )
    assert cert.key_type == "ec-256"
    runtime = ConfigBuilder().build(cert, settings, db=db)
    raw = yaml.safe_load(runtime.config_path.read_text(encoding="utf-8"))
    assert raw["certificates"][0]["targets"][0]["type"] == "aliyun_cdn"
    assert raw["certificates"][0]["targets"][0]["domains"] == ["cdn.example.com"]
    assert runtime.env["ALIYUN_AK"] == "A"
