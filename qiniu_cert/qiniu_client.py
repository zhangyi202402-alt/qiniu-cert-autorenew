"""七牛融合 CDN API 客户端：双端点、双鉴权（fusion QBox / api Qiniu）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import requests
from qiniu import Auth
from qiniu.auth import QiniuMacAuth


class QiniuApiError(Exception):
    """七牛 API 返回 HTTP >= 400 时抛出。"""

    def __init__(self, status: int, body: Any, url: str) -> None:
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} {url}: {body}")


class QiniuClient:
    """
    七牛 CDN 证书与域名 HTTPS 配置客户端。

    端点不可混用：
    - fusion.qiniuapi.com：证书上传/列表/删除，鉴权 QBox（body 不参与签名）
    - api.qiniu.com：域名 HTTPS 配置，鉴权 Qiniu（含 X-Qiniu-Date，有 body 时 body 参与签名）
    """

    FUSION_BASE = "https://fusion.qiniuapi.com"
    API_BASE = "https://api.qiniu.com"

    def __init__(self, access_key: str, secret_key: str, timeout: int = 30) -> None:
        self.ak = access_key
        self.sk = secret_key
        self.timeout = timeout
        self._qbox_auth = Auth(access_key, secret_key)
        self._qiniu_auth = QiniuMacAuth(access_key, secret_key)

    def fusion_request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
    ) -> tuple[int, Any]:
        """向 fusion 端点发起请求（QBox 鉴权）。"""
        base = f"{self.FUSION_BASE}{path}"
        if params:
            base = f"{base}?{urlencode(params)}"
        # QBox 签名仅含 path+query，JSON body 不参与
        token = self._qbox_auth.token_of_request(base, body=None, content_type=None)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"QBox {token}",
        }
        resp = requests.request(
            method,
            base,
            headers=headers,
            json=body,
            timeout=self.timeout,
        )
        try:
            payload = resp.json() if resp.text else {}
        except json.JSONDecodeError:
            payload = resp.text
        if resp.status_code >= 400:
            raise QiniuApiError(resp.status_code, payload, base)
        return resp.status_code, payload

    def api_request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
    ) -> tuple[int, Any]:
        """向 api 端点发起请求（Qiniu 鉴权）。"""
        url = f"{self.API_BASE}{path}"
        headers: dict[str, str] = {}
        raw = None
        x_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        headers["X-Qiniu-Date"] = x_date
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        token = self._qiniu_auth.token_of_request(
            method=method,
            host="api.qiniu.com",
            url=url,
            qheaders=self._qiniu_auth.qiniu_headers(headers),
            content_type=headers.get("Content-Type", ""),
            body=raw,
        )
        headers["Authorization"] = f"Qiniu {token}"
        resp = requests.request(
            method,
            url,
            headers=headers,
            data=raw,
            timeout=self.timeout,
        )
        try:
            payload = resp.json() if resp.text else {}
        except json.JSONDecodeError:
            payload = resp.text
        if resp.status_code >= 400:
            raise QiniuApiError(resp.status_code, payload, url)
        return resp.status_code, payload

    def upload_ssl_cert(
        self,
        name: str,
        private_key: str,
        certificate_chain: str,
        common_name: str | None = None,
    ) -> str:
        """上传证书到 fusion，返回 certID。"""
        body: dict[str, str] = {
            "name": name,
            "pri": private_key,
            "ca": certificate_chain,
        }
        if common_name:
            body["commonName"] = common_name
        _, payload = self.fusion_request("POST", "/sslcert", body=body)
        cert_id = payload.get("certID") or payload.get("certid")
        if not cert_id:
            raise QiniuApiError(200, payload, f"{self.FUSION_BASE}/sslcert")
        return str(cert_id)

    def get_domain(self, domain: str) -> dict:
        """查询 CDN 域名配置。"""
        _, payload = self.api_request("GET", f"/domain/{domain}")
        return payload if isinstance(payload, dict) else {}

    def domain_https_enabled(self, domain: str) -> bool:
        """判断域名是否已开启 HTTPS（决定用 sslize 还是 httpsconf）。"""
        info = self.get_domain(domain)
        https = info.get("https") or info.get("Https")
        if isinstance(https, dict):
            if https.get("enable") is True or https.get("Enable") is True:
                return True
            if https.get("certId") or https.get("certid"):
                return True
        protocol = str(info.get("protocol") or info.get("Protocol") or "").lower()
        return protocol == "https"

    def _parse_tls_versions(self, tls_versions: str | list[str] | None) -> list[str] | None:
        """七牛 API 要求 tlsVersions 为数组，如 ["TLSv1.2", "TLSv1.3"]。"""
        if not tls_versions:
            return None
        if isinstance(tls_versions, list):
            return tls_versions
        parts = [p.strip() for p in tls_versions.replace(",", "/").split("/") if p.strip()]
        return parts or None

    def _https_body(
        self,
        cert_id: str,
        force_https: bool,
        http2_enable: bool,
        tls_versions: str | list[str] | None,
    ) -> dict:
        """构建 sslize/httpsconf 请求体（扁平格式，非 quick-start 的 nested ssl）。"""
        body = {
            "certId": cert_id,
            "forceHttps": force_https,
            "http2Enable": http2_enable,
        }
        parsed_tls = self._parse_tls_versions(tls_versions)
        if parsed_tls:
            body["tlsVersions"] = parsed_tls
        return body

    def bind_https(
        self,
        domain: str,
        cert_id: str,
        force_https: bool = True,
        http2_enable: bool = True,
        tls_versions: str | None = "TLSv1.2/TLSv1.3",
        first_time: bool | None = None,
    ) -> dict:
        """
        绑定证书到 CDN 域名。

        - 首次开启 HTTPS：PUT /domain/{d}/sslize
        - 已开 HTTPS 换证：PUT /domain/{d}/httpsconf
        """
        body = self._https_body(cert_id, force_https, http2_enable, tls_versions)
        if first_time is None:
            first_time = not self.domain_https_enabled(domain)
        path = f"/domain/{domain}/sslize" if first_time else f"/domain/{domain}/httpsconf"
        _, payload = self.api_request("PUT", path, body=body)
        return payload if isinstance(payload, dict) else {"code": 200}

    def delete_cert(self, cert_id: str) -> dict:
        """删除 fusion 上的证书（须未绑定任何域名）。"""
        _, payload = self.fusion_request("DELETE", f"/sslcert/{cert_id}")
        return payload if isinstance(payload, dict) else {"code": 200}
