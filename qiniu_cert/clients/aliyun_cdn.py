"""阿里云 CDN OpenAPI 客户端（RPC + HMAC-SHA1）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from typing import Any
from urllib.parse import quote

import requests

API_VERSION = "2018-05-10"
DEFAULT_ENDPOINT = "https://cdn.aliyuncs.com"
_SUCCESS_CODES = frozenset({"", "OK", "Success", "200"})


class AliyunCdnError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def _percent_encode(value: str) -> str:
    return quote(str(value), safe="~")


def _rpc_error_message(payload: dict[str, Any], fallback: str) -> str:
    return str(payload.get("Message") or payload.get("message") or fallback)


class AliyunCdnClient:
    """CDN 域名 HTTPS 证书相关 RPC 调用。"""

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
        if resp.status_code >= 400:
            code = payload.get("Code")
            raise AliyunCdnError(
                _rpc_error_message(payload, resp.text[:300]),
                code=str(code) if code is not None else str(resp.status_code),
            )
        code = payload.get("Code")
        if code is None:
            return
        code_s = str(code)
        if code_s in _SUCCESS_CODES:
            return
        raise AliyunCdnError(
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
            raise AliyunCdnError(f"invalid JSON response: {resp.text[:200]}") from exc

        if not isinstance(payload, dict):
            raise AliyunCdnError(f"unexpected response type: {type(payload)}")

        self._raise_if_error(resp, payload)
        return payload

    def set_cdn_domain_ssl_certificate(
        self,
        *,
        domain_name: str,
        cert_name: str,
        ssl_pub: str,
        ssl_pri: str,
    ) -> dict[str, Any]:
        """上传 PEM 并启用 HTTPS（CertType=upload）。"""
        return self._rpc(
            "SetCdnDomainSSLCertificate",
            {
                "DomainName": domain_name,
                "CertName": cert_name,
                "CertType": "upload",
                "SSLProtocol": "on",
                "SSLPub": ssl_pub,
                "SSLPri": ssl_pri,
            },
        )

    def describe_domain_certificate_info(
        self,
        *,
        domain_name: str,
    ) -> dict[str, Any]:
        return self._rpc(
            "DescribeDomainCertificateInfo",
            {"DomainName": domain_name},
        )
