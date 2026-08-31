"""crypto 单测。"""

from __future__ import annotations

import base64
import os

import pytest

from app.crypto import CryptoError, decrypt, encrypt, master_key_bytes, sanitize_error


def test_encrypt_decrypt_roundtrip():
    key = os.urandom(32)
    token = encrypt("hello-secret", key)
    assert decrypt(token, key) == "hello-secret"


def test_master_key_bytes():
    raw = os.urandom(32)
    b64 = base64.b64encode(raw).decode()
    assert master_key_bytes(b64) == raw


def test_bad_key_length():
    with pytest.raises(CryptoError):
        encrypt("x", b"short")


def test_decrypt_tampered():
    key = os.urandom(32)
    token = encrypt("secret", key)
    with pytest.raises(CryptoError):
        decrypt(token[:-4] + "xxxx", key)


def test_sanitize_error():
    msg = sanitize_error("failed key=abcdefghi", ["abcdefghi"])
    assert "***" in msg
    assert "abcdefghi" not in msg
