"""Pydantic / 表单 schema。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

DOMAIN_RE = re.compile(
    r"^(\*\.)?([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


def parse_domain_lines(text: str) -> list[str]:
    domains: list[str] = []
    for line in text.splitlines():
        d = line.strip().lower().rstrip(".")
        if not d:
            continue
        if not DOMAIN_RE.match(d):
            raise ValueError(f"invalid domain: {d}")
        domains.append(d)
    if not domains:
        raise ValueError("at least one domain required")
    return domains


def primary_domain_of(issue_domains: list[str]) -> str:
    for d in issue_domains:
        if not d.startswith("*."):
            return d
    return issue_domains[0].lstrip("*.")


def parse_deploy_targets_form(
    deploy_type: str,
    *,
    cdn_domains_text: str = "",
    clb_targets_text: str = "",
) -> list[dict]:
    """从表单解析部署目标。CLB 为每行 JSON 或 CSV: region,lb_id,port[,probe_host]。"""
    if deploy_type in ("qiniu_cdn", "aliyun_cdn"):
        domains = parse_domain_lines(cdn_domains_text)
        return [{"type": deploy_type, "domains": domains, "https": {}}]
    if deploy_type == "aliyun_clb":
        targets: list[dict] = []
        for line in clb_targets_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                obj = json.loads(line)
                obj["type"] = "aliyun_clb"
                targets.append(obj)
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                raise ValueError(
                    "CLB 行格式: region_id,load_balancer_id[,port][,probe_host]"
                )
            port = int(parts[2]) if len(parts) > 2 and parts[2] else 443
            probe = parts[3] if len(parts) > 3 and parts[3] else None
            targets.append(
                {
                    "type": "aliyun_clb",
                    "region_id": parts[0],
                    "load_balancer_id": parts[1],
                    "listener_port": port,
                    "domain_extensions": [],
                    "probe_host": probe,
                }
            )
        if not targets:
            raise ValueError("至少一行 CLB 目标")
        return targets
    raise ValueError(f"unsupported deploy_type: {deploy_type}")


@dataclass
class RegisterForm:
    email: str
    password: str


@dataclass
class LoginForm:
    email: str
    password: str


@dataclass
class CertCreateForm:
    name: str
    acme_email: str
    profile_id: int
    issue_domains: list[str]
    deploy_targets: list[dict]
    renew_days: int = 15


@dataclass
class CertUpdateForm:
    name: str
    acme_email: str
    profile_id: int
    issue_domains: list[str]
    deploy_targets: list[dict]
    renew_days: int = 15


def format_deploy_targets_for_form(
    deploy_type: str, targets: list[dict]
) -> dict[str, str]:
    """编辑页回填：cdn_domains / clb_targets 文本。"""
    if deploy_type in ("qiniu_cdn", "aliyun_cdn"):
        domains: list[str] = []
        for t in targets or []:
            if t.get("type") == deploy_type:
                domains.extend(t.get("domains") or [])
        return {"cdn_domains": "\n".join(domains), "clb_targets": ""}
    lines: list[str] = []
    for t in targets or []:
        if t.get("type") != "aliyun_clb":
            continue
        parts = [
            str(t.get("region_id") or ""),
            str(t.get("load_balancer_id") or ""),
            str(t.get("listener_port") or 443),
        ]
        if t.get("probe_host"):
            parts.append(str(t["probe_host"]))
        lines.append(",".join(parts))
    return {"cdn_domains": "", "clb_targets": "\n".join(lines)}


def parse_suggested_targets_text(deploy_type: str, text: str) -> list[dict] | None:
    text = (text or "").strip()
    if not text:
        return None
    return parse_deploy_targets_form(
        deploy_type,
        cdn_domains_text=text if deploy_type in ("qiniu_cdn", "aliyun_cdn") else "",
        clb_targets_text=text if deploy_type == "aliyun_clb" else "",
    )
