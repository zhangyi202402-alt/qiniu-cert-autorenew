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


def test_upload_server_certificate_from_cas_parses_id(monkeypatch) -> None:
    client = AliyunSlbClient("ak", "sk")
    captured: dict = {}

    def fake_request(method, url, **kwargs):
        captured["data"] = kwargs.get("data")

        class R:
            status_code = 200
            text = "{}"

            def json(self):
                return {"ServerCertificateId": "slb-cert-from-cas", "RequestId": "r1"}

        return R()

    monkeypatch.setattr(client.session, "request", fake_request)
    cid = client.upload_server_certificate_from_cas(
        region_id="cn-beijing",
        aliyun_certificate_id="775123",
        aliyun_certificate_region_id="cn-hangzhou",
        server_certificate_name="mycert01",
    )
    assert cid == "slb-cert-from-cas"
    assert captured["data"]["AliCloudCertificateId"] == "775123"
    assert captured["data"]["AliCloudCertificateRegionId"] == "cn-hangzhou"
    assert captured["data"]["RegionId"] == "cn-beijing"
    assert "ServerCertificate" not in captured["data"]
    assert "PrivateKey" not in captured["data"]


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


def test_rpc_raises_on_business_error_code(monkeypatch) -> None:
    from qiniu_cert.clients.aliyun_slb import AliyunSlbError

    client = AliyunSlbClient("ak", "sk")

    def fake_request(method, url, **kwargs):
        class R:
            status_code = 200
            text = "{}"

            def json(self):
                return {"Code": "InvalidParameter", "Message": "bad param", "RequestId": "r"}

        return R()

    monkeypatch.setattr(client.session, "request", fake_request)
    try:
        client.delete_server_certificate(region_id="cn-hangzhou", server_certificate_id="x")
        raise AssertionError("expected AliyunSlbError")
    except AliyunSlbError as exc:
        assert exc.code == "InvalidParameter"
        assert "bad param" in str(exc)


def test_rpc_raises_on_http_400(monkeypatch) -> None:
    from qiniu_cert.clients.aliyun_slb import AliyunSlbError

    client = AliyunSlbClient("ak", "sk")

    def fake_request(method, url, **kwargs):
        class R:
            status_code = 400
            text = "bad"

            def json(self):
                return {"Code": "Throttling", "Message": "slow down"}

        return R()

    monkeypatch.setattr(client.session, "request", fake_request)
    try:
        client.delete_server_certificate(region_id="cn-hangzhou", server_certificate_id="x")
        raise AssertionError("expected AliyunSlbError")
    except AliyunSlbError as exc:
        assert exc.code == "Throttling"
