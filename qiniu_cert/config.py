"""config.yaml 加载与环境变量展开。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_env(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.environ.get(key, match.group(0))

    return ENV_PATTERN.sub(repl, value)


def _expand(obj: Any) -> Any:
    if isinstance(obj, str):
        return _expand_env(obj)
    if isinstance(obj, dict):
        return {k: _expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand(v) for v in obj]
    return obj


@dataclass
class HttpsConfig:
    force_https: bool = True
    http2_enable: bool = True
    tls_versions: str = "TLSv1.2/TLSv1.3"


@dataclass
class AcmeConfig:
    email: str = ""
    ca: str = "letsencrypt_test"
    key_type: str = "ec-256"
    renew_days: int = 30  # 证书到期前 N 天触发续签（acme.sh --days 负值）
    no_ari: bool = False  # true 时禁用 Let's Encrypt ARI，严格按 renew_days


@dataclass
class CertificateConfig:
    name: str
    issue_domains: list[str]
    dns_provider: str
    qiniu_cdn_domains: list[str]
    https: HttpsConfig = field(default_factory=HttpsConfig)
    dns_env: dict[str, str] = field(default_factory=dict)


@dataclass
class AppConfig:
    qiniu_ak: str
    qiniu_sk: str
    certificates: list[CertificateConfig]
    state_file: Path
    acme: AcmeConfig = field(default_factory=AcmeConfig)
    notify_webhook: str = ""
    notify_provider: str = "auto"
    probe_retries: int = 15
    probe_interval_sec: int = 60
    old_cert_cleanup_days: int = 7
    min_valid_days: int = 30


def _resolve_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (config_path.parent / path).resolve()


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = _expand(raw)

    qiniu = data.get("qiniu", {})
    paths = data.get("paths", {})
    deploy = data.get("deploy", {})
    notify = data.get("notify", {})
    acme_raw = data.get("acme", {})

    certs: list[CertificateConfig] = []
    for item in data.get("certificates", []):
        https_raw = item.get("https", {})
        certs.append(
            CertificateConfig(
                name=item["name"],
                issue_domains=list(item["issue_domains"]),
                dns_provider=item["dns_provider"],
                qiniu_cdn_domains=list(item["qiniu_cdn_domains"]),
                https=HttpsConfig(
                    force_https=https_raw.get("force_https", True),
                    http2_enable=https_raw.get("http2_enable", True),
                    tls_versions=https_raw.get("tls_versions", "TLSv1.2/TLSv1.3"),
                ),
                dns_env=dict(item.get("dns_env", {})),
            )
        )

    return AppConfig(
        qiniu_ak=qiniu.get("access_key", ""),
        qiniu_sk=qiniu.get("secret_key", ""),
        certificates=certs,
        state_file=_resolve_path(config_path, paths.get("state_file", ".local/state/state.json")),
        acme=AcmeConfig(
            email=acme_raw.get("email", ""),
            ca=acme_raw.get("ca", "letsencrypt_test"),
            key_type=acme_raw.get("key_type", "ec-256"),
            renew_days=int(acme_raw.get("renew_days", 30)),
            no_ari=bool(acme_raw.get("no_ari", False)),
        ),
        notify_webhook=notify.get("webhook", ""),
        notify_provider=str(notify.get("provider", "auto") or "auto"),
        probe_retries=int(deploy.get("probe_retries", 15)),
        probe_interval_sec=int(deploy.get("probe_interval_sec", 60)),
        old_cert_cleanup_days=int(deploy.get("old_cert_cleanup_days", 7)),
        min_valid_days=int(deploy.get("min_valid_days", 30)),
    )


def find_cert_by_issue_domain(config: AppConfig, domain: str) -> CertificateConfig | None:
    for cert in config.certificates:
        if domain in cert.issue_domains or domain.rstrip(".") == cert.issue_domains[0]:
            return cert
        base = cert.issue_domains[0].lstrip("*.")
        if domain == base or domain.endswith("." + base):
            return cert
    return None


def find_cert_by_cdn_domain(config: AppConfig, cdn_domain: str) -> CertificateConfig | None:
    for cert in config.certificates:
        if cdn_domain in cert.qiniu_cdn_domains:
            return cert
    return None
