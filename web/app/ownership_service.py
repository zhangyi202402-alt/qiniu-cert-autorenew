"""域名归属 DNS TXT 验证。"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.repositories import cert_repo
from qiniu_cert.dns_check import query_txt


@dataclass
class OwnershipResult:
    ok: bool
    values: list[str]
    message: str = ""


def _normalize_txt_value(raw: str) -> str:
    """去掉引号与空白，合并 dig 拆段。"""
    return raw.replace('"', "").strip()


def _txt_candidates(values: list[str]) -> list[str]:
    """将 dig 输出规范为可比对的 TXT 字符串列表（精确匹配用）。"""
    out: list[str] = []
    for v in values:
        norm = _normalize_txt_value(v)
        if not norm:
            continue
        out.append(norm)
        # dig 偶发把一条 TXT 拆成带空格的拼接，再拆成 token 级候选
        parts = [p.strip() for p in norm.split() if p.strip()]
        if len(parts) > 1:
            out.extend(parts)
    return out


class OwnershipService:
    def generate_token(self) -> str:
        return secrets.token_urlsafe(32)

    def verification_host(self, primary_domain: str) -> str:
        return f"_qcert-verify.{primary_domain.rstrip('.')}"

    def expected_txt(self, token: str) -> str:
        return f"qcert-verify={token}"

    def check(self, host: str, token: str) -> OwnershipResult:
        expected = self.expected_txt(token)
        values = query_txt(host)
        if values and values[0].startswith("(dig error"):
            return OwnershipResult(ok=False, values=values, message=values[0])
        for candidate in _txt_candidates(values):
            # 精确相等，禁止子串匹配（避免 qcert-verify=abc 命中 abcdef）
            if candidate == expected:
                return OwnershipResult(ok=True, values=values, message="matched")
        return OwnershipResult(
            ok=False,
            values=values,
            message="TXT not found or token mismatch",
        )

    def verify_certificate(self, db: Session, cert_id: int) -> OwnershipResult:
        cert = cert_repo.get(db, cert_id)
        if not cert:
            return OwnershipResult(ok=False, values=[], message="certificate not found")
        result = self.check(cert.verification_host, cert.verification_token)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cert.last_verification_at = now
        if result.ok:
            cert.verification_status = "verified"
            if not cert.verified_at:
                cert.verified_at = now
        else:
            if cert.verification_status == "verified" or cert.verified_at:
                cert.verification_status = "lost"
            else:
                cert.verification_status = "unverified"
        cert_repo.save(db, cert)
        return result
