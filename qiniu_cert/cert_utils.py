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


def split_pem_certificates(fullchain_pem: str) -> list[str]:
    """将 PEM 文本拆成单张证书（含 BEGIN/END 行）。"""
    certs: list[str] = []
    for block in fullchain_pem.split("-----END CERTIFICATE-----"):
        block = block.strip()
        if not block:
            continue
        certs.append(block + "\n-----END CERTIFICATE-----\n")
    return certs


def _load_leaf_cert(fullchain_pem: str) -> x509.Certificate:
    certs = split_pem_certificates(fullchain_pem)
    if not certs:
        raise DeployError("no certificate found in fullchain PEM")
    return x509.load_pem_x509_certificate(certs[0].encode(), default_backend())


def cas_user_certificate_pem(fullchain_pem: str) -> str:
    """证书服务自定义上传：保留 acme fullchain 全部 PEM（含交叉签中间证）。"""
    parts = split_pem_certificates(fullchain_pem)
    if not parts:
        raise DeployError("no certificate found in fullchain PEM")
    return "".join(parts)


def sanitize_cas_certificate_name(name: str, *, max_len: int = 63) -> str:
    """CAS UploadUserCertificate Name：最长 63，允许字母数字下划线等。"""
    cleaned = []
    for ch in name:
        if ch.isalnum() or ch in "._-*":
            cleaned.append(ch)
        else:
            cleaned.append("-")
    out = "".join(cleaned).strip("-._*")
    return (out or "cert")[:max_len]


def clb_server_certificate_pem(fullchain_pem: str) -> str:
    """
    CLB UploadServerCertificate 用的公钥链：叶证书 + 中间证，去掉公信根/交叉根。

    Let's Encrypt 新链可能含 Root YR 等交叉证书；整链上传会报
    CertificateFormatInvalid。叶证书若自签则原样保留。
    """
    kept: list[str] = []
    for idx, pem in enumerate(split_pem_certificates(fullchain_pem)):
        cert = x509.load_pem_x509_certificate(pem.encode(), default_backend())
        if idx > 0 and cert.subject == cert.issuer:
            break
        cn_attrs = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        cn = str(cn_attrs[0].value) if cn_attrs else ""
        if idx > 0 and (cn.startswith("Root ") or cn.startswith("ISRG Root")):
            break
        kept.append(pem)
        if idx == 0 and cert.subject == cert.issuer:
            break
    if not kept:
        raise DeployError("no usable certificates for CLB upload")
    return "".join(kept)


def sanitize_server_certificate_name(name: str, *, max_len: int = 80) -> str:
    """CLB ServerCertificateName：字母开头，仅字母数字 . _ -。"""
    cleaned = []
    for ch in name:
        if ch.isalnum() or ch in "._-":
            cleaned.append(ch)
        else:
            cleaned.append("-")
    out = "".join(cleaned).strip("-._")
    if not out or not out[0].isalpha():
        out = f"cert-{out}" if out else "cert"
    return out[:max_len]


def assert_certificate_rsa(fullchain_pem: str, *, min_bits: int = 2048) -> None:
    """叶证书公钥必须为 RSA，且位数不少于 min_bits（CLB 默认要求 ≥2048）。"""
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod

    leaf = _load_leaf_cert(fullchain_pem)
    pub = leaf.public_key()
    if not isinstance(pub, rsa_mod.RSAPublicKey):
        raise DeployError("CLB requires RSA certificate; ECC/other key types are not supported")
    bits = pub.key_size
    if bits < min_bits:
        raise DeployError(f"CLB requires RSA>={min_bits} bits; got {bits}")


def ensure_rsa_private_key_pkcs1(pem: str, *, min_bits: int = 2048) -> str:
    """
    将私钥转为 CLB 所需的未加密 PKCS#1（BEGIN RSA PRIVATE KEY）。

    若已是 PKCS#1 RSA 则原样规范化输出；非 RSA 或位数不足则抛 DeployError。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod

    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, rsa_mod.RSAPrivateKey):
        raise DeployError("CLB requires RSA private key; got non-RSA key")
    if key.key_size < min_bits:
        raise DeployError(f"CLB requires RSA private key>={min_bits} bits; got {key.key_size}")
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


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


def tls_not_after(
    domain: str,
    timeout: float = 10.0,
    server_hostname: str | None = None,
    connect_host: str | None = None,
) -> datetime | None:
    """
    读取线上 443 证书 notAfter（naive UTC），失败返回 None。

    connect_host: TCP 连接地址（如 CLB VIP）；默认等于 domain。
    server_hostname: TLS SNI；默认等于 domain。
    """
    host = connect_host or domain
    sni = server_hostname or domain
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=sni) as ssock:
                der = ssock.getpeercert(binary_form=True)
                if not der:
                    return None
                cert = x509.load_der_x509_certificate(der, default_backend())
                not_after = getattr(cert, "not_valid_after_utc", cert.not_valid_after)
                if not_after.tzinfo is None:
                    not_after = not_after.replace(tzinfo=timezone.utc)
                return not_after.replace(tzinfo=None)
    except Exception:
        return None


def tls_probe(
    domain: str,
    min_valid_days: int = 30,
    timeout: float = 10.0,
    server_hostname: str | None = None,
    connect_host: str | None = None,
) -> tuple[bool, str]:
    """
    直连 443 探活：SNI、证书链、剩余有效期。

    connect_host: TCP 连接地址（如 CLB VIP）；默认等于 domain。
    server_hostname: TLS SNI / 校验名；默认等于 domain。
    """
    host = connect_host or domain
    sni = server_hostname or domain
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=sni) as ssock:
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
