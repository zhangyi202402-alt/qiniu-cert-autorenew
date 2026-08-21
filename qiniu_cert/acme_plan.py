"""acme.sh 签发计划：从 config 导出 DNS 环境与逐证书签发参数。"""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from qiniu_cert.config import AppConfig, load_config, effective_key_type, iter_targets


@dataclass(frozen=True)
class CertIssuePlan:
    """单张 ACME 证书的签发与 deploy 参数。"""

    name: str
    primary_domain: str
    dns_hook: str
    domain_args: str  # 已 shell 转义的 "-d a -d b"
    key_type: str  # 配置中的 key_type（如 rsa-2048 / ec-256）
    keylength: str  # 传给 acme.sh --keylength（如 2048 / ec-256）
    cert_dir: str  # acme 证书目录名，如 example.com_ecc 或 example.com
    deploy_hook: str  # acme.sh --deploy-hook 名称


def dns_hook_name(provider: str) -> str:
    name = provider if provider.startswith("dns_") else f"dns_{provider}"
    return name.lower()


def primary_issue_domain(issue_domains: list[str]) -> str:
    """acme 目录与 --deploy -d 使用的主域名（优先非通配符）。"""
    for domain in issue_domains:
        if not domain.startswith("*."):
            return domain
    return issue_domains[0].lstrip("*.")


def domain_args_shell(issue_domains: list[str]) -> str:
    return " ".join(f"-d {shlex.quote(d)}" for d in issue_domains)


def acme_cert_dir(primary_domain: str, key_type: str) -> str:
    """acme.sh 证书目录：EC 为 {domain}_ecc，RSA 为 {domain}。"""
    kt = key_type.lower()
    if kt.startswith("ec") or "ecc" in kt:
        return f"{primary_domain}_ecc"
    return primary_domain


def acme_keylength(key_type: str) -> str:
    """
    将配置 key_type 映射为 acme.sh --keylength 合法值。

    acme.sh 只接受 2048/3072/4096/8192 或 ec-256/ec-384/ec-521，
    不接受 rsa-2048 这类前缀写法。
    """
    raw = key_type.strip()
    kt = raw.lower().replace("_", "-")
    aliases = {
        "rsa-2048": "2048",
        "rsa2048": "2048",
        "2048": "2048",
        "rsa-3072": "3072",
        "rsa3072": "3072",
        "3072": "3072",
        "rsa-4096": "4096",
        "rsa4096": "4096",
        "4096": "4096",
        "rsa-8192": "8192",
        "rsa8192": "8192",
        "8192": "8192",
        "ec-256": "ec-256",
        "ec256": "ec-256",
        "ecc": "ec-256",
        "ec-384": "ec-384",
        "ec384": "ec-384",
        "ec-521": "ec-521",
        "ec521": "ec-521",
    }
    if kt in aliases:
        return aliases[kt]
    if kt.startswith("rsa-") and kt[4:].isdigit():
        return kt[4:]
    if kt.isdigit():
        return kt
    if kt.startswith("ec-"):
        return kt
    raise ValueError(f"unsupported key_type for acme.sh --keylength: {key_type!r}")


def acme_days_arg(config: AppConfig) -> str:
    """到期前 renew_days 天续签 → acme.sh 使用负值（相对证书到期日）。"""
    return str(-abs(config.acme.renew_days))


def sync_renew_days(config_path: str | Path, acme_home: Path) -> list[str]:
    """更新已签发域名的 Le_RenewalDays / Le_NextRenewTime（不重新申请证书）。"""
    from datetime import timedelta, timezone

    from cryptography import x509

    config = load_config(config_path)
    days_arg = acme_days_arg(config)
    renewal_days = -abs(config.acme.renew_days)
    updated: list[str] = []

    for plan in build_issue_plans(config):
        conf = acme_home / plan.cert_dir / f"{plan.primary_domain}.conf"
        chain = acme_home / plan.cert_dir / "fullchain.cer"
        if not conf.is_file() or not chain.is_file():
            continue

        pem = chain.read_bytes()
        cert = x509.load_pem_x509_certificate(pem)
        not_after = getattr(cert, "not_valid_after_utc", cert.not_valid_after)
        if not_after.tzinfo is None:
            not_after = not_after.replace(tzinfo=timezone.utc)
        next_renew = not_after + timedelta(days=renewal_days)
        next_ts = int(next_renew.timestamp())
        next_str = next_renew.strftime("%Y-%m-%dT%H:%M:%SZ")

        lines: list[str] = []
        for line in conf.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0] if "=" in line else ""
            if key in {"Le_RenewalDays", "Le_NextRenewTime", "Le_NextRenewTimeStr"}:
                continue
            lines.append(line)
        lines.append(f"Le_RenewalDays='{days_arg}'")
        lines.append(f"Le_NextRenewTime='{next_ts}'")
        lines.append(f"Le_NextRenewTimeStr='{next_str}'")
        conf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        updated.append(plan.primary_domain)

    return updated


def deploy_hook_for(cert) -> str:
    """选择 acme deploy-hook：纯 CLB 用 clb_wrapper，其余用 qiniu_wrapper（router 仍可部署 CLB）。"""
    types = {t.type for t in iter_targets(cert)}
    if types == {"aliyun_clb"}:
        return "clb_wrapper"
    return "qiniu_wrapper"


def build_issue_plans(config: AppConfig) -> list[CertIssuePlan]:
    plans: list[CertIssuePlan] = []
    for cert in config.certificates:
        primary = primary_issue_domain(cert.issue_domains)
        key_type = effective_key_type(cert, config.acme)
        keylength = acme_keylength(key_type)
        plans.append(
            CertIssuePlan(
                name=cert.name,
                primary_domain=primary,
                dns_hook=dns_hook_name(cert.dns_provider),
                domain_args=domain_args_shell(cert.issue_domains),
                key_type=key_type,
                keylength=keylength,
                cert_dir=acme_cert_dir(primary, key_type),
                deploy_hook=deploy_hook_for(cert),
            )
        )
    return plans


def dns_env_shell(config_path: str) -> str:
    """输出可 eval 的 export 语句，供 bash setup 加载 DNS 凭据。"""
    config = load_config(config_path)
    lines: list[str] = []
    seen: set[str] = set()
    for cert in config.certificates:
        for env_name in cert.dns_env.values():
            if env_name in seen:
                continue
            seen.add(env_name)
            value = os.environ.get(env_name, "")
            if value:
                lines.append(f"export {env_name}={shlex.quote(value)}")
    return "\n".join(lines)


def _print_issue_plans(config_path: str) -> None:
    for plan in build_issue_plans(load_config(config_path)):
        row = "\t".join(
            [
                plan.name,
                plan.primary_domain,
                plan.dns_hook,
                plan.domain_args,
                plan.keylength,
                plan.cert_dir,
                plan.deploy_hook,
            ]
        )
        print(row)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: acme_plan export-dns <config.yaml>", file=sys.stderr)
        print("       acme_plan list-certs <config.yaml>", file=sys.stderr)
        print("       acme_plan sync-renew-days <config.yaml> <acme_home>", file=sys.stderr)
        return 2
    cmd, config_path = sys.argv[1], sys.argv[2]
    if cmd == "export-dns":
        print(dns_env_shell(config_path))
        return 0
    if cmd == "list-certs":
        _print_issue_plans(config_path)
        return 0
    if cmd == "sync-renew-days":
        if len(sys.argv) < 4:
            print("usage: acme_plan sync-renew-days <config.yaml> <acme_home>", file=sys.stderr)
            return 2
        updated = sync_renew_days(config_path, Path(sys.argv[3]))
        for domain in updated:
            print(domain)
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
