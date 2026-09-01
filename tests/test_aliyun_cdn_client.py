"""阿里云 CDN OpenAPI 客户端单测。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from qiniu_cert.clients.aliyun_cdn import AliyunCdnClient, AliyunCdnError


def test_set_cdn_domain_ssl_certificate_request():
    client = AliyunCdnClient("ak", "sk")
    session = MagicMock()
    client.session = session
    session.request.return_value.json.return_value = {"RequestId": "req-1"}
    session.request.return_value.status_code = 200

    client.set_cdn_domain_ssl_certificate(
        domain_name="cdn.example.com",
        cert_name="test-cert",
        ssl_pub="-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----",
        ssl_pri="-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----",
    )

    session.request.assert_called_once()
    call = session.request.call_args
    assert call[0][0] == "POST"
    data = call.kwargs["data"]
    assert data["Action"] == "SetCdnDomainSSLCertificate"
    assert data["DomainName"] == "cdn.example.com"
    assert data["CertName"] == "test-cert"
    assert data["CertType"] == "upload"
    assert data["SSLProtocol"] == "on"
    assert "SSLPub" in data
    assert "SSLPri" in data
    assert "Signature" in data


def test_rpc_error_raises():
    client = AliyunCdnClient("ak", "sk")
    session = MagicMock()
    client.session = session
    session.request.return_value.status_code = 200
    session.request.return_value.json.return_value = {
        "Code": "InvalidDomain",
        "Message": "domain offline",
    }

    with pytest.raises(AliyunCdnError, match="domain offline"):
        client.set_cdn_domain_ssl_certificate(
            domain_name="bad.example.com",
            cert_name="x",
            ssl_pub="pub",
            ssl_pri="pri",
        )
