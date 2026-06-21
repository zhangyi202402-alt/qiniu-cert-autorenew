"""证书解析、SAN 校验、TLS/forceHttps 探活。"""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.backends import default_backend


class DeployError(Exception):
    """部署流程业务错误（SAN 不匹配、探活失败、部分域名失败等）。"""


def read_pem(path: Path) -> str:
    """读取 PEM 文本文件。"""
    return path.read_text(encoding="utf-8")


def cert_covers_domain(fullchain_pem: str, domain: str) -> bool:
    """
    检查叶子证书 SAN/CN 是否覆盖目标 CDN 域名。

    支持精确匹配与通配符 *.example.com（不匹配 example.com 本身需 SAN 含 example.com）。
    """
    certs = []
    for block in fullchain_pem.split("-----END CERTIFICATE-----"):
        block = block.strip()
        if not block:
            continue
        pem = block + "\n-----END CERTIFICATE-----\n"
        certs.append(x509.load_pem_x509_certificate(pem.encode(), default_backend()))
    if not certs:
        return False

    leaf = certs[0]
    try:
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        names = {n.value.lower() for n in san.value if isinstance(n.value, str)}
    except x509.ExtensionNotFound:
        names = set()

    cn_attrs = leaf.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    if cn_attrs:
        names.add(str(cn_attrs[0].value).lower())

    target = domain.lower().rstrip(".")
    if target in names:
        return True
    for name in names:
        if name.startswith("*."):
            suffix = name[1:]  # ".example.com"
            if target == name[2:] or target.endswith(suffix):
                return True
    return False


def tls_probe(
    domain: str,
    min_valid_days: int = 30,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """
    直连 CDN 443 探活：SNI、证书链、剩余有效期。

    返回 (是否通过, 说明信息)。
    """
    context = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                der = ssock.getpeercert(binary_form=True)
                if not der:
                    return False, "no peer certificate"
                cert = x509.load_der_x509_certificate(der, default_backend())
                not_after = getattr(cert, "not_valid_after_utc", cert.not_valid_after)
                if not_after.tzinfo is None:
                    not_after = not_after.replace(tzinfo=timezone.utc)
                remaining = (not_after - datetime.now(timezone.utc)).days
                if remaining < min_valid_days:
                    return False, f"notAfter in {remaining} days (< {min_valid_days})"
                return True, f"ok, expires in {remaining} days"
    except Exception as exc:
        return False, str(exc)


def probe_force_https(domain: str, timeout: float = 10.0) -> tuple[bool, str]:
    """
    检查 HTTP 访问是否 301/302 等到 HTTPS。

    用于验证七牛 forceHttps 配置是否生效。
    """
    import urllib.error
    import urllib.request

    url = f"http://{domain}/"
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            location = resp.headers.get("Location", "")
            if resp.status in (301, 302, 307, 308) and location.lower().startswith("https://"):
                return True, location
            return False, f"unexpected status {resp.status}"
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "")
        if exc.code in (301, 302, 307, 308) and location.lower().startswith("https://"):
            return True, location
        return False, f"http error {exc.code}"
    except Exception as exc:
        return False, str(exc)
