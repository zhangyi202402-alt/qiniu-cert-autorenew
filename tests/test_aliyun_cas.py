"""Aliyun CAS client unit tests."""

from __future__ import annotations

from qiniu_cert.clients.aliyun_cas import AliyunCasClient, AliyunCasError


def test_upload_user_certificate_parses_cert_id(monkeypatch) -> None:
    client = AliyunCasClient("ak", "sk")

    def fake_request(method, url, **kwargs):
        class R:
            status_code = 200
            text = "{}"

            def json(self):
                return {"CertId": 775123, "RequestId": "r1"}

        return R()

    monkeypatch.setattr(client.session, "request", fake_request)
    cert_id = client.upload_user_certificate(
        name="test-cert",
        cert="-----BEGIN CERTIFICATE-----\nA\n-----END CERTIFICATE-----",
        key="-----BEGIN RSA PRIVATE KEY-----\nB\n-----END RSA PRIVATE KEY-----",
    )
    assert cert_id == "775123"


def test_upload_user_certificate_raises_on_error(monkeypatch) -> None:
    client = AliyunCasClient("ak", "sk")

    def fake_request(method, url, **kwargs):
        class R:
            status_code = 200
            text = "{}"

            def json(self):
                return {"Code": "InvalidParameter", "Message": "bad cert"}

        return R()

    monkeypatch.setattr(client.session, "request", fake_request)
    try:
        client.upload_user_certificate(name="x", cert="c", key="k")
        raise AssertionError("expected AliyunCasError")
    except AliyunCasError as exc:
        assert exc.code == "InvalidParameter"
