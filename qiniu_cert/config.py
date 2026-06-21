"""config.yaml 加载与环境变量展开。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 支持 ${ENV_VAR} 形式引用环境变量
ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_env(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.environ.get(key, match.group(0))

    return ENV_PATTERN.sub(repl, value)


def _expand(obj: Any) -> Any:
    """递归展开配置中的环境变量引用。"""
    if isinstance(obj, str):
        return _expand_env(obj)
    if isinstance(obj, dict):
        return {k: _expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand(v) for v in obj]
    return obj


@dataclass
class HttpsConfig:
    """CDN 域名 HTTPS 绑定参数（对应 sslize/httpsconf body）。"""

    force_https: bool = True
    http2_enable: bool = True
    tls_versions: str = "TLSv1.2/TLSv1.3"


@dataclass
class CertificateConfig:
    """一张 ACME 证书及其关联的七牛 CDN 域名。"""

    name: str
    issue_domains: list[str]       # acme.sh -d 参数（可含通配符）
    dns_provider: str              # acme dns 插件名，如 tencent → dns_tencent
    qiniu_cdn_domains: list[str]   # 需绑定此证书的 CDN 加速域名
    https: HttpsConfig = field(default_factory=HttpsConfig)
    dns_env: dict[str, str] = field(default_factory=dict)  # DNS API 凭据对应的环境变量名


@dataclass
class AppConfig:
    """应用全局配置。"""

    qiniu_ak: str
    qiniu_sk: str
    certificates: list[CertificateConfig]
    state_file: Path
    log_file: Path
    notify_webhook: str = ""
    notify_provider: str = "auto"  # dingtalk | feishu | auto（按 URL 自动识别）
    probe_retries: int = 15          # 探活次数，默认 15×60s ≈ 15min
    probe_interval_sec: int = 60
    old_cert_cleanup_days: int = 7   # 换绑后等待天数再 DELETE 旧证
    min_valid_days: int = 30         # 探活要求证书至少剩余有效天数
    acme_email: str = ""
    acme_ca: str = "letsencrypt_test"  # Phase 1: letsencrypt_test；生产: letsencrypt


def load_config(path: str | Path) -> AppConfig:
    """从 YAML 加载并展开环境变量。"""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    data = _expand(raw)

    qiniu = data.get("qiniu", {})
    paths = data.get("paths", {})
    deploy = data.get("deploy", {})
    notify = data.get("notify", {})
    acme = data.get("acme", {})

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
        state_file=Path(paths.get("state_file", "/var/lib/qiniu-cert/state.json")),
        log_file=Path(paths.get("log_file", "/var/log/acme-qiniu.log")),
        notify_webhook=notify.get("webhook", ""),
        notify_provider=str(notify.get("provider", "auto") or "auto"),
        probe_retries=int(deploy.get("probe_retries", 15)),
        probe_interval_sec=int(deploy.get("probe_interval_sec", 60)),
        old_cert_cleanup_days=int(deploy.get("old_cert_cleanup_days", 7)),
        min_valid_days=int(deploy.get("min_valid_days", 30)),
        acme_email=acme.get("email", ""),
        acme_ca=acme.get("ca", "letsencrypt_test"),
    )


def find_cert_by_issue_domain(config: AppConfig, domain: str) -> CertificateConfig | None:
    """
    根据 acme deploy hook 传入的域名匹配证书记录。

    支持：精确匹配 issue_domains、主域后缀匹配（含通配符证书场景）。
    """
    for cert in config.certificates:
        if domain in cert.issue_domains or domain.rstrip(".") == cert.issue_domains[0]:
            return cert
        base = cert.issue_domains[0].lstrip("*.")
        if domain == base or domain.endswith("." + base):
            return cert
    return None
