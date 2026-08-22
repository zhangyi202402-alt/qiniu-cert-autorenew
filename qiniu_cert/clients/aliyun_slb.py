"""阿里云传统型负载均衡（CLB/SLB）OpenAPI 客户端（RPC + HMAC-SHA1）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import uuid
from typing import Any
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

API_VERSION = "2014-05-15"
DEFAULT_ENDPOINT = "https://slb.aliyuncs.com"
_SUCCESS_CODES = frozenset({"", "OK", "Success", "200"})


class AliyunSlbError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def _percent_encode(value: str) -> str:
    # 阿里云签名要求：保留字符外编码，且 + → %20，* → %2A，~ 不编码
    return quote(str(value), safe="~")


def _rpc_error_message(payload: dict[str, Any], fallback: str) -> str:
    return str(payload.get("Message") or payload.get("message") or fallback)


class AliyunSlbClient:
    """SLB 证书相关 RPC 调用。"""

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        session: requests.Session | None = None,
    ) -> None:
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.endpoint = endpoint.rstrip("/")
        self.session = session or requests.Session()

    def _sign(self, params: dict[str, str]) -> str:
        sorted_items = sorted(params.items())
        canonicalized = "&".join(
            f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_items
        )
        string_to_sign = f"POST&%2F&{_percent_encode(canonicalized)}"
        digest = hmac.new(
            (self.access_key_secret + "&").encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _raise_if_error(self, resp: requests.Response, payload: dict[str, Any]) -> None:
        """
        HTTP 非 2xx，或 JSON 带业务错误 Code 时抛出 AliyunSlbError。

        成功响应通常只有 RequestId + 业务字段，不含错误 Code。
        """
        if resp.status_code >= 400:
            code = payload.get("Code")
            raise AliyunSlbError(
                _rpc_error_message(payload, resp.text[:300]),
                code=str(code) if code is not None else str(resp.status_code),
            )

        code = payload.get("Code")
        if code is None:
            return
        code_s = str(code)
        if code_s in _SUCCESS_CODES:
            return
        raise AliyunSlbError(
            _rpc_error_message(payload, code_s),
            code=code_s,
        )

    def _rpc(self, action: str, extra: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, str] = {
            "Format": "JSON",
            "Version": API_VERSION,
            "AccessKeyId": self.access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid.uuid4()),
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Action": action,
        }
        for key, value in extra.items():
            if value is None:
                continue
            params[key] = str(value)
        params["Signature"] = self._sign(params)

        resp = self.session.request(
            "POST",
            self.endpoint,
            data=params,
            timeout=60,
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise AliyunSlbError(f"invalid JSON response: {resp.text[:200]}") from exc

        if not isinstance(payload, dict):
            raise AliyunSlbError(f"unexpected response type: {type(payload)}")

        self._raise_if_error(resp, payload)
        return payload

    def upload_server_certificate(
        self,
        *,
        region_id: str,
        server_certificate: str,
        private_key: str,
        server_certificate_name: str,
    ) -> str:
        payload = self._rpc(
            "UploadServerCertificate",
            {
                "RegionId": region_id,
                "ServerCertificate": server_certificate,
                "PrivateKey": private_key,
                "ServerCertificateName": server_certificate_name,
            },
        )
        cert_id = payload.get("ServerCertificateId")
        if not cert_id:
            raise AliyunSlbError(f"UploadServerCertificate missing ServerCertificateId: {payload}")
        return str(cert_id)

    def upload_server_certificate_from_cas(
        self,
        *,
        region_id: str,
        aliyun_certificate_id: str,
        aliyun_certificate_region_id: str,
        server_certificate_name: str,
    ) -> str:
        """
        将证书服务中的证书部署到 CLB 地域，返回 ServerCertificateId。

        AliCloudCertificateRegionId 为证书服务地域（中国内地固定 cn-hangzhou），
        与 CLB 实例所在 RegionId 不同。
        """
        payload = self._rpc(
            "UploadServerCertificate",
            {
                "RegionId": region_id,
                "AliCloudCertificateId": aliyun_certificate_id,
                "AliCloudCertificateRegionId": aliyun_certificate_region_id,
                "ServerCertificateName": server_certificate_name,
            },
        )
        cert_id = payload.get("ServerCertificateId")
        if not cert_id:
            raise AliyunSlbError(
                f"UploadServerCertificate (CAS) missing ServerCertificateId: {payload}"
            )
        return str(cert_id)

    def describe_load_balancer_attribute(
        self,
        *,
        region_id: str,
        load_balancer_id: str,
    ) -> dict[str, Any]:
        return self._rpc(
            "DescribeLoadBalancerAttribute",
            {
                "RegionId": region_id,
                "LoadBalancerId": load_balancer_id,
            },
        )

    def set_https_listener_certificate(
        self,
        *,
        region_id: str,
        load_balancer_id: str,
        listener_port: int,
        server_certificate_id: str,
    ) -> None:
        self._rpc(
            "SetLoadBalancerHTTPSListenerAttribute",
            {
                "RegionId": region_id,
                "LoadBalancerId": load_balancer_id,
                "ListenerPort": listener_port,
                "ServerCertificateId": server_certificate_id,
            },
        )

    def describe_domain_extensions(
        self,
        *,
        region_id: str,
        load_balancer_id: str,
        listener_port: int,
    ) -> list[dict[str, Any]]:
        payload = self._rpc(
            "DescribeDomainExtensions",
            {
                "RegionId": region_id,
                "LoadBalancerId": load_balancer_id,
                "ListenerPort": listener_port,
            },
        )
        block = payload.get("DomainExtensions") or {}
        items = block.get("DomainExtension") or []
        if isinstance(items, dict):
            items = [items]
        return list(items)

    def set_domain_extension_certificate(
        self,
        *,
        region_id: str,
        domain_extension_id: str,
        server_certificate_id: str,
    ) -> None:
        self._rpc(
            "SetDomainExtensionAttribute",
            {
                "RegionId": region_id,
                "DomainExtensionId": domain_extension_id,
                "ServerCertificateId": server_certificate_id,
            },
        )

    def delete_server_certificate(
        self,
        *,
        region_id: str,
        server_certificate_id: str,
    ) -> None:
        self._rpc(
            "DeleteServerCertificate",
            {
                "RegionId": region_id,
                "ServerCertificateId": server_certificate_id,
            },
        )
