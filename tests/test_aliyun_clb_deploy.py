"""CLB deploy orchestration tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from datetime import datetime, timedelta, timezone

from qiniu_cert.config import (
    AppConfig,
    CertificateConfig,
    TargetAliyunClb,
)
from qiniu_cert.providers.aliyun_clb import AliyunClbProvider


def _rsa_leaf_and_key(sans: list[str]) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, sans[0])])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(n) for n in sans]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    fullchain = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return fullchain, key_pem


def test_clb_deploy_uploads_sets_listener_and_extension(tmp_path: Path, monkeypatch) -> None:
    fullchain, key_pem = _rsa_leaf_and_key(["www.example.com", "api.example.com"])
    cfg = AppConfig(
        qiniu_ak="",
        qiniu_sk="",
        aliyun_ak="ak",
        aliyun_sk="sk",
        certificates=[],
        state_file=tmp_path / "state.json",
        probe_retries=1,
        probe_interval_sec=0,
        min_valid_days=1,
    )
    provider = AliyunClbProvider(cfg)
    mock = MagicMock()
    mock.upload_server_certificate.return_value = "cert-new"
    mock.describe_domain_extensions.return_value = [
        {"Domain": "api.example.com", "DomainExtensionId": "de-1"}
    ]
    provider.client = mock

    monkeypatch.setattr(
        "qiniu_cert.providers.aliyun_clb.tls_probe",
        lambda *a, **k: (True, "ok"),
    )

    cert_cfg = CertificateConfig(
        name="clb1",
        issue_domains=["www.example.com"],
        dns_provider="dns_ali",
        key_type="rsa-2048",
    )
    target = TargetAliyunClb(
        region_id="cn-hangzhou",
        load_balancer_id="lb-1",
        listener_port=443,
        domain_extensions=["api.example.com"],
        probe_host="www.example.com",
    )
    new_id = provider.deploy(cert_cfg, target, "www.example.com", key_pem, fullchain)
    assert new_id == "cert-new"
    mock.upload_server_certificate.assert_called_once()
    mock.set_https_listener_certificate.assert_called_once()
    mock.set_domain_extension_certificate.assert_called_once_with(
        region_id="cn-hangzhou",
        domain_extension_id="de-1",
        server_certificate_id="cert-new",
    )
    state = provider.state.load()
    assert "clb:cn-hangzhou:lb-1:443" in state
    assert state["clb:cn-hangzhou:lb-1:443"].current_cert_id == "cert-new"
    assert state["clb:cn-hangzhou:lb-1:443:api.example.com"].current_cert_id == "cert-new"
