"""ownership 单测。"""

from __future__ import annotations

from unittest.mock import patch

from app.ownership_service import OwnershipService


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
