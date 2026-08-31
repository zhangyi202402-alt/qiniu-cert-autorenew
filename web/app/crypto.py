"""AES-256-GCM 凭据加解密。"""

from __future__ import annotations

import base64
import os


class CryptoError(Exception):
    """加解密失败（不携带明文）。"""


def master_key_bytes(web_master_key: str) -> bytes:
    """解析 base64 主密钥，必须为 32 字节。"""
    try:
        key = base64.b64decode(web_master_key.strip())
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("invalid WEB_MASTER_KEY encoding") from exc
    if len(key) != 32:
        raise CryptoError("WEB_MASTER_KEY must decode to 32 bytes")
    return key


def encrypt(plaintext: str, master_key: bytes) -> str:
    """AES-256-GCM。返回 base64(nonce + ciphertext + tag)。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(master_key) != 32:
        raise CryptoError("master key must be 32 bytes")
    nonce = os.urandom(12)
    aesgcm = AESGCM(master_key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(ciphertext_b64: str, master_key: bytes) -> str:
    """解密；失败抛 CryptoError，不泄露明文。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(master_key) != 32:
        raise CryptoError("master key must be 32 bytes")
    try:
        raw = base64.b64decode(ciphertext_b64.strip())
        nonce, ct = raw[:12], raw[12:]
        aesgcm = AESGCM(master_key)
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
    except CryptoError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("decrypt failed") from exc


def sanitize_error(message: str, secrets: list[str] | None = None) -> str:
    """从错误信息中抹除已知密钥片段。"""
    out = message
    for secret in secrets or []:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "***")
    return out
