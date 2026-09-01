"""阿里云 CDN deploy orchestration tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from qiniu_cert.config import AppConfig, CertificateConfig, TargetAliyunCdn
from qiniu_cert.providers.aliyun_cdn import AliyunCdnProvider, aliyun_cdn_state_key


def _ec_leaf_and_key(sans: list[str]) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
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
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return fullchain, key_pem


def test_aliyun_cdn_deploy_sets_cert_per_domain(tmp_path: Path, monkeypatch) -> None:
    fullchain, key_pem = _ec_leaf_and_key(["cdn.example.com"])
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
    provider = AliyunCdnProvider(cfg)
    mock_client = MagicMock()
    provider.client = mock_client

    monkeypatch.setattr(
        "qiniu_cert.providers.aliyun_cdn.tls_probe",
        lambda *a, **k: (True, "ok"),
    )
    monkeypatch.setattr(
        "qiniu_cert.providers.aliyun_cdn.probe_force_https",
        lambda *a, **k: (True, "ok"),
    )

    cert_cfg = CertificateConfig(
        name="cdn1",
        issue_domains=["cdn.example.com"],
        dns_provider="dns_ali",
        key_type="ec-256",
    )
    target = TargetAliyunCdn(domains=["cdn.example.com"])
    cert_name = provider.deploy(cert_cfg, target, "cdn.example.com", key_pem, fullchain)
    assert cert_name
    mock_client.set_cdn_domain_ssl_certificate.assert_called_once()
    call = mock_client.set_cdn_domain_ssl_certificate.call_args.kwargs
    assert call["domain_name"] == "cdn.example.com"
    assert call["ssl_pub"] == fullchain
    assert call["ssl_pri"] == key_pem
    state = provider.state.load()
    key = aliyun_cdn_state_key("cdn.example.com")
    assert key in state
    assert state[key].current_cert_id == cert_name


def test_aliyun_cdn_deploy_san_mismatch_raises(tmp_path: Path) -> None:
    fullchain, key_pem = _ec_leaf_and_key(["other.example.com"])
    cfg = AppConfig(
        qiniu_ak="",
        qiniu_sk="",
        aliyun_ak="ak",
        aliyun_sk="sk",
        certificates=[],
        state_file=tmp_path / "state.json",
    )
    provider = AliyunCdnProvider(cfg)
    cert_cfg = CertificateConfig(
        name="cdn1",
        issue_domains=["cdn.example.com"],
        dns_provider="dns_ali",
    )
    target = TargetAliyunCdn(domains=["cdn.example.com"])
    with pytest.raises(Exception, match="does not cover"):
        provider.deploy(cert_cfg, target, "cdn.example.com", key_pem, fullchain, skip_probe=True)


def test_deploy_service_aliyun_cdn_only_without_qiniu_keys(
    tmp_path: Path, monkeypatch
) -> None:
    """纯 aliyun_cdn 配置不应因空七牛 AK/SK 在 DeployService 构造阶段失败。"""
    from qiniu_cert.deploy import DeployService

    fullchain, key_pem = _ec_leaf_and_key(["cdn.example.com"])
    key_path = tmp_path / "key.pem"
    fullchain_path = tmp_path / "full.pem"
    key_path.write_text(key_pem, encoding="utf-8")
    fullchain_path.write_text(fullchain, encoding="utf-8")

    cfg = AppConfig(
        qiniu_ak="",
        qiniu_sk="",
        aliyun_ak="ak",
        aliyun_sk="sk",
        certificates=[
            CertificateConfig(
                name="cdn1",
                issue_domains=["cdn.example.com"],
                dns_provider="dns_ali",
                targets=[TargetAliyunCdn(domains=["cdn.example.com"])],
            )
        ],
        state_file=tmp_path / "state.json",
        probe_retries=1,
        probe_interval_sec=0,
    )
    mock_provider = MagicMock()
    mock_provider.deploy.return_value = "aliyun-cert-1"
    monkeypatch.setattr(
        "qiniu_cert.deploy.DeployService._get_aliyun_cdn_provider",
        lambda self: mock_provider,
    )

    service = DeployService(cfg)
    cert_id = service.deploy_from_files("cdn.example.com", key_path, fullchain_path)
    assert cert_id == "aliyun-cert-1"
    assert service._qiniu is None
