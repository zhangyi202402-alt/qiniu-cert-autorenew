"""ownership 单测。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Certificate
from app.ownership_service import OwnershipService


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_generate_token_and_host():
    svc = OwnershipService()
    token = svc.generate_token()
    assert len(token) >= 32
    assert svc.verification_host("example.com") == "_qcert-verify.example.com"
    assert svc.expected_txt(token) == f"qcert-verify={token}"


def test_check_match():
    svc = OwnershipService()
    token = "abcTOKEN"
    with patch("app.ownership_service.query_txt", return_value=[f"qcert-verify={token}"]):
        result = svc.check("_qcert-verify.example.com", token)
    assert result.ok


def test_check_mismatch():
    svc = OwnershipService()
    with patch("app.ownership_service.query_txt", return_value=["other"]):
        result = svc.check("_qcert-verify.example.com", "token")
    assert not result.ok


def test_check_rejects_prefix_substring():
    """禁止 qcert-verify=abc 匹配 qcert-verify=abcdef。"""
    svc = OwnershipService()
    with patch(
        "app.ownership_service.query_txt",
        return_value=["qcert-verify=abcdef"],
    ):
        result = svc.check("_qcert-verify.example.com", "abc")
    assert not result.ok


def test_verify_cli_imported_keeps_verified(db):
    cert = Certificate(
        user_id=1,
        profile_id=1,
        name="cli",
        primary_domain="example.com",
        issue_domains=["example.com"],
        deploy_targets=[],
        verification_token="tok",
        verification_host="_qcert-verify.example.com",
        verification_status="verified",
        status="active",
        acme_home="/tmp/acme",
        acme_email="ops@example.com",
        state_json={"cli_imported": True},
    )
    db.add(cert)
    db.commit()

    svc = OwnershipService()
    with patch("app.ownership_service.query_txt", return_value=[]):
        result = svc.verify_certificate(db, cert.id)
    db.refresh(cert)
    assert not result.ok
    assert cert.verification_status == "verified"
