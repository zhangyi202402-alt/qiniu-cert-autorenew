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
class TargetQiniuCdn:
    """七牛 CDN 部署目标。"""

    domains: list[str]
    https: HttpsConfig = field(default_factory=HttpsConfig)
    type: str = "qiniu_cdn"


@dataclass
class TargetAliyunClb:
    """阿里云 CLB HTTPS 监听部署目标。"""

    region_id: str
    load_balancer_id: str
    listener_port: int
    domain_extensions: list[str] = field(default_factory=list)
    probe_host: str | None = None
    type: str = "aliyun_clb"


DeployTarget = TargetQiniuCdn | TargetAliyunClb


@dataclass
class CertificateConfig:
    name: str
    issue_domains: list[str]
    dns_provider: str
    qiniu_cdn_domains: list[str] = field(default_factory=list)
    https: HttpsConfig = field(default_factory=HttpsConfig)
    dns_env: dict[str, str] = field(default_factory=dict)
    key_type: str | None = None
    targets: list[DeployTarget] = field(default_factory=list)


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
    aliyun_ak: str = ""
    aliyun_sk: str = ""


def _resolve_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (config_path.parent / path).resolve()


def _parse_https(https_raw: dict[str, Any] | None) -> HttpsConfig:
    https_raw = https_raw or {}
    return HttpsConfig(
        force_https=https_raw.get("force_https", True),
        http2_enable=https_raw.get("http2_enable", True),
        tls_versions=https_raw.get("tls_versions", "TLSv1.2/TLSv1.3"),
    )


def _parse_targets(
    item: dict[str, Any],
    default_https: HttpsConfig,
) -> list[DeployTarget]:
    raw_targets = item.get("targets")
    if not raw_targets:
        return []

    targets: list[DeployTarget] = []
    for t in raw_targets:
        ttype = str(t.get("type", "")).strip()
        if ttype == "qiniu_cdn":
            domains = list(t.get("domains") or [])
            if not domains:
                raise ValueError("qiniu_cdn target requires domains")
            https = _parse_https(t.get("https")) if t.get("https") else default_https
            targets.append(TargetQiniuCdn(domains=domains, https=https))
        elif ttype == "aliyun_clb":
            region_id = str(t.get("region_id", "")).strip()
            lb_id = str(t.get("load_balancer_id", "")).strip()
            port = int(t.get("listener_port", 443))
            if not region_id or not lb_id:
                raise ValueError("aliyun_clb target requires region_id and load_balancer_id")
            targets.append(
                TargetAliyunClb(
                    region_id=region_id,
                    load_balancer_id=lb_id,
                    listener_port=port,
                    domain_extensions=list(t.get("domain_extensions") or []),
                    probe_host=t.get("probe_host"),
                )
            )
        else:
            raise ValueError(f"unknown target type: {ttype}")
    return targets


def _is_rsa_2048(key_type: str) -> bool:
    normalized = key_type.strip().lower().replace("_", "-")
    return normalized in {"rsa-2048", "2048", "rsa2048"}


def effective_key_type(cert: CertificateConfig, acme: AcmeConfig) -> str:
    """证书级 key_type 优先，否则用全局 acme.key_type。"""
    if cert.key_type:
        return str(cert.key_type)
    return acme.key_type


def iter_targets(cert: CertificateConfig) -> list[DeployTarget]:
    """返回部署目标；无 targets 时用旧字段 qiniu_cdn_domains 合成。"""
    if cert.targets:
        return list(cert.targets)
    if cert.qiniu_cdn_domains:
        return [TargetQiniuCdn(domains=list(cert.qiniu_cdn_domains), https=cert.https)]
    return []


def _resolve_aliyun_creds(aliyun: dict[str, Any]) -> tuple[str, str]:
    ak = (
        str(aliyun.get("access_key") or "").strip()
        or os.environ.get("ALIYUN_AK", "").strip()
        or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    )
    sk = (
        str(aliyun.get("secret_key") or "").strip()
        or os.environ.get("ALIYUN_SK", "").strip()
        or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    )
    # 若 YAML 里仍是未展开的 ${...}，当作空
    if ak.startswith("${"):
        ak = (
            os.environ.get("ALIYUN_AK", "").strip()
            or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
        )
    if sk.startswith("${"):
        sk = (
            os.environ.get("ALIYUN_SK", "").strip()
            or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
        )
    return ak, sk


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = _expand(raw)

    qiniu = data.get("qiniu", {})
    aliyun = data.get("aliyun", {})
    paths = data.get("paths", {})
    deploy = data.get("deploy", {})
    notify = data.get("notify", {})
    acme_raw = data.get("acme", {})

    acme = AcmeConfig(
        email=acme_raw.get("email", ""),
        ca=acme_raw.get("ca", "letsencrypt_test"),
        key_type=acme_raw.get("key_type", "ec-256"),
        renew_days=int(acme_raw.get("renew_days", 30)),
        no_ari=bool(acme_raw.get("no_ari", False)),
    )

    certs: list[CertificateConfig] = []
    for item in data.get("certificates", []):
        https = _parse_https(item.get("https", {}))
        qiniu_domains = list(item.get("qiniu_cdn_domains") or [])
        targets = _parse_targets(item, default_https=https)
        cert = CertificateConfig(
            name=item["name"],
            issue_domains=list(item["issue_domains"]),
            dns_provider=item["dns_provider"],
            qiniu_cdn_domains=qiniu_domains,
            https=https,
            dns_env=dict(item.get("dns_env", {})),
            key_type=item.get("key_type"),
            targets=targets,
        )
        # 兼容：旧配置只有 qiniu_cdn_domains
        if not cert.targets and qiniu_domains:
            pass  # iter_targets 会合成
        elif not cert.targets and not qiniu_domains:
            raise ValueError(
                f"certificate {cert.name!r} needs targets or qiniu_cdn_domains"
            )

        for t in iter_targets(cert):
            if t.type == "aliyun_clb" and not _is_rsa_2048(effective_key_type(cert, acme)):
                raise ValueError(
                    f"certificate {cert.name!r} targets aliyun_clb but key_type "
                    f"must be rsa-2048 (got {effective_key_type(cert, acme)!r})"
                )
        certs.append(cert)

    aliyun_ak, aliyun_sk = _resolve_aliyun_creds(aliyun)

    return AppConfig(
        qiniu_ak=qiniu.get("access_key", ""),
        qiniu_sk=qiniu.get("secret_key", ""),
        aliyun_ak=aliyun_ak,
        aliyun_sk=aliyun_sk,
        certificates=certs,
        state_file=_resolve_path(config_path, paths.get("state_file", ".local/state/state.json")),
        acme=acme,
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
        for t in iter_targets(cert):
            if isinstance(t, TargetQiniuCdn) and cdn_domain in t.domains:
                return cert
    return None
