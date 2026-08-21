from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from qiniu_cert.cert_utils import DeployError, cert_covers_domain, tls_probe
from qiniu_cert.config import AppConfig, CertificateConfig, HttpsConfig, load_config
from qiniu_cert.deploy import DeployService
from qiniu_cert.qiniu_client import QiniuApiError, QiniuClient
from qiniu_cert.state import DomainState, StateStore


def _make_cert_pem(sans: list[str], cn: str = "example.com") -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    alt_names = x509.SubjectAlternativeName([x509.DNSName(n) for n in sans])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
        .add_extension(alt_names, critical=False)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_cert_covers_domain_wildcard():
    pem = _make_cert_pem(["*.example.com", "example.com"])
    assert cert_covers_domain(pem, "cdn.example.com")
    assert cert_covers_domain(pem, "example.com")
    assert not cert_covers_domain(pem, "other.com")


def test_load_config_expands_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QINIU_AK", "ak-test")
    monkeypatch.setenv("QINIU_SK", "sk-test")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
qiniu:
  access_key: "${QINIU_AK}"
  secret_key: "${QINIU_SK}"
certificates:
  - name: t
    issue_domains: [example.com]
    dns_provider: tencent
    qiniu_cdn_domains: [cdn.example.com]
paths:
  state_file: /tmp/state.json
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.qiniu_ak == "ak-test"
    assert cfg.qiniu_sk == "sk-test"


def test_load_config_resolves_relative_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("QINIU_AK", "ak")
    monkeypatch.setenv("QINIU_SK", "sk")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
qiniu:
  access_key: "${QINIU_AK}"
  secret_key: "${QINIU_SK}"
certificates:
  - name: t
    issue_domains: [example.com]
    dns_provider: dns_ali
    qiniu_cdn_domains: [cdn.example.com]
paths:
  state_file: .local/state/state.json
acme:
  key_type: ec-256
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.state_file == (tmp_path / ".local/state/state.json").resolve()
    assert cfg.acme.key_type == "ec-256"


def test_state_store_roundtrip(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.update_after_deploy("cdn.example.com", "cert-new", cleanup_days=7)
    state = store.get("cdn.example.com")
    assert state.current_cert_id == "cert-new"
    pending = store.list_pending_cleanup()
    assert pending == []


def test_state_pending_cleanup(tmp_path):
    store = StateStore(tmp_path / "state.json")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "cdn.example.com": {
                    "current_cert_id": "new",
                    "previous_cert_id": "old",
                    "previous_cleanup_after": past,
                    "last_deploy_at": "",
                }
            }
        ),
        encoding="utf-8",
    )
    assert store.list_pending_cleanup() == [("cdn.example.com", "old")]


def test_deploy_success(tmp_path):
    pem = _make_cert_pem(["cdn.example.com"])
    key_path = tmp_path / "key.pem"
    fullchain = tmp_path / "full.pem"
    key_path.write_text("fake-key", encoding="utf-8")
    fullchain.write_text(pem, encoding="utf-8")

    cfg = AppConfig(
        qiniu_ak="ak",
        qiniu_sk="sk",
        certificates=[
            CertificateConfig(
                name="t",
                issue_domains=["example.com"],
                dns_provider="tencent",
                qiniu_cdn_domains=["cdn.example.com"],
                https=HttpsConfig(),
            )
        ],
        state_file=tmp_path / "state.json",
        probe_retries=1,
        probe_interval_sec=0,
    )
    service = DeployService(cfg)

    with patch.object(service.client, "upload_ssl_cert", return_value="cert-123"), patch.object(
        service.client, "bind_https", return_value={"code": 200}
    ), patch.object(service.qiniu, "_probe_with_retry", return_value=(True, "ok")):
        cert_id = service.deploy_from_files("example.com", key_path, fullchain)
    assert cert_id == "cert-123"
    assert service.state.get("cdn.example.com").current_cert_id == "cert-123"


def test_deploy_single_domain_probe_fail_keeps_state(tmp_path):
    pem = _make_cert_pem(["cdn.example.com"])
    key_path = tmp_path / "key.pem"
    fullchain = tmp_path / "full.pem"
    key_path.write_text("fake-key", encoding="utf-8")
    fullchain.write_text(pem, encoding="utf-8")

    state_file = tmp_path / "state.json"
    store = StateStore(state_file)
    store.update_after_deploy("cdn.example.com", "old-cert")

    cfg = AppConfig(
        qiniu_ak="ak",
        qiniu_sk="sk",
        certificates=[
            CertificateConfig(
                name="t",
                issue_domains=["example.com"],
                dns_provider="tencent",
                qiniu_cdn_domains=["cdn.example.com"],
            )
        ],
        state_file=state_file,
        probe_retries=1,
    )
    service = DeployService(cfg)
    bind = MagicMock(return_value={"code": 200})

    with patch.object(service.client, "upload_ssl_cert", return_value="cert-new"), patch.object(
        service.client, "bind_https", bind
    ), patch.object(service.qiniu, "_probe_with_retry", return_value=(False, "probe timeout")):
        with pytest.raises(DeployError):
            service.deploy_from_files("example.com", key_path, fullchain)

    assert service.state.get("cdn.example.com").current_cert_id == "old-cert"
    rollback_calls = [c for c in bind.call_args_list if c.kwargs.get("cert_id") == "old-cert"]
    assert not rollback_calls


def test_deploy_multi_domain_partial_failure(tmp_path):
    pem = _make_cert_pem(["a.example.com", "b.example.com"])
    key_path = tmp_path / "key.pem"
    fullchain = tmp_path / "full.pem"
    key_path.write_text("fake-key", encoding="utf-8")
    fullchain.write_text(pem, encoding="utf-8")

    state_file = tmp_path / "state.json"
    store = StateStore(state_file)
    store.update_after_deploy("a.example.com", "old-a")
    store.update_after_deploy("b.example.com", "old-b")

    cfg = AppConfig(
        qiniu_ak="ak",
        qiniu_sk="sk",
        certificates=[
            CertificateConfig(
                name="t",
                issue_domains=["example.com"],
                dns_provider="tencent",
                qiniu_cdn_domains=["a.example.com", "b.example.com"],
            )
        ],
        state_file=state_file,
        probe_retries=1,
        probe_interval_sec=0,
    )
    service = DeployService(cfg)

    def probe_side_effect(domain: str, check_force_https: bool) -> tuple[bool, str]:
        if domain == "a.example.com":
            return True, "ok"
        return False, "probe failed"

    with patch.object(service.client, "upload_ssl_cert", return_value="cert-new"), patch.object(
        service.client, "bind_https", return_value={"code": 200}
    ), patch.object(service.qiniu, "_probe_with_retry", side_effect=probe_side_effect):
        with pytest.raises(DeployError, match="failed b.example.com"):
            service.deploy_from_files("example.com", key_path, fullchain)

    assert service.state.get("a.example.com").current_cert_id == "cert-new"
    assert service.state.get("b.example.com").current_cert_id == "old-b"


def test_qiniu_api_error_str():
    err = QiniuApiError(401, {"code": 401001}, "https://example.com")
    assert "401" in str(err)
