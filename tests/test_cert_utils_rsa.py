"""RSA / PKCS#1 helpers for CLB uploads."""

from __future__ import annotations

import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from qiniu_cert.cert_utils import (
    DeployError,
    assert_certificate_rsa,
    ensure_rsa_private_key_pkcs1,
)


def _make_leaf_pem(key) -> str:
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "example.com")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("example.com")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_ensure_rsa_pkcs1_accepts_rsa() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pkcs8 = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    out = ensure_rsa_private_key_pkcs1(pkcs8)
    assert "BEGIN RSA PRIVATE KEY" in out
    assert "BEGIN PRIVATE KEY" not in out.split("BEGIN RSA")[0] or "BEGIN RSA PRIVATE KEY" in out


def test_ensure_rsa_rejects_ec() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    with pytest.raises(DeployError, match="RSA"):
        ensure_rsa_private_key_pkcs1(pem)


def test_assert_certificate_rsa_rejects_ec() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = _make_leaf_pem(key)
    with pytest.raises(DeployError, match="RSA"):
        assert_certificate_rsa(pem)


def test_assert_certificate_rsa_accepts_rsa() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = _make_leaf_pem(key)
    assert_certificate_rsa(pem)
