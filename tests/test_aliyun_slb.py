"""Aliyun SLB client unit tests."""

from __future__ import annotations

from qiniu_cert.clients.aliyun_slb import AliyunSlbClient


def test_upload_server_certificate_parses_id(monkeypatch) -> None:
    client = AliyunSlbClient("ak", "sk")

    def fake_request(method, url, **kwargs):
        class R:
            status_code = 200
            text = "{}"

            def json(self):
                return {"ServerCertificateId": "15015-cn-hangzhou", "RequestId": "r1"}

        return R()

    monkeypatch.setattr(client.session, "request", fake_request)
    cid = client.upload_server_certificate(
        region_id="cn-hangzhou",
        server_certificate="-----BEGIN CERTIFICATE-----\nA\n-----END CERTIFICATE-----",
        private_key="-----BEGIN RSA PRIVATE KEY-----\nB\n-----END RSA PRIVATE KEY-----",
        server_certificate_name="t1",
    )
    assert cid == "15015-cn-hangzhou"


def test_describe_domain_extensions_list(monkeypatch) -> None:
    client = AliyunSlbClient("ak", "sk")

    def fake_request(method, url, **kwargs):
        class R:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "DomainExtensions": {
                        "DomainExtension": [
                            {
                                "DomainExtensionId": "de-1",
                                "Domain": "api.example.com",
                                "ServerCertificateId": "old",
                            }
                        ]
                    }
                }

        return R()

    monkeypatch.setattr(client.session, "request", fake_request)
    items = client.describe_domain_extensions(
        region_id="cn-hangzhou",
        load_balancer_id="lb-1",
        listener_port=443,
    )
    assert items[0]["Domain"] == "api.example.com"
    assert items[0]["DomainExtensionId"] == "de-1"


def test_set_https_listener_certificate_ok(monkeypatch) -> None:
    client = AliyunSlbClient("ak", "sk")
    called = {}

    def fake_request(method, url, **kwargs):
        called["data"] = kwargs.get("data")

        class R:
            status_code = 200
            text = "{}"

            def json(self):
                return {"RequestId": "r2"}

        return R()

    monkeypatch.setattr(client.session, "request", fake_request)
    client.set_https_listener_certificate(
        region_id="cn-hangzhou",
        load_balancer_id="lb-1",
        listener_port=443,
        server_certificate_id="id-new",
    )
    assert called["data"]["Action"] == "SetLoadBalancerHTTPSListenerAttribute"
    assert called["data"]["ServerCertificateId"] == "id-new"
