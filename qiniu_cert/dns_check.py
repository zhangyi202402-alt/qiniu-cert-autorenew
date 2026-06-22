"""ACME DNS-01：查询 _acme-challenge TXT 记录（签发前/后核对）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from qiniu_cert.acme_plan import build_issue_plans, primary_issue_domain
from qiniu_cert.config import CertificateConfig, load_config


def acme_challenge_host(issue_domain: str) -> str:
    """DNS-01 挑战主机名（与 acme.sh 一致：去掉 *. 前缀）。"""
    host = issue_domain.lstrip("*.")
    return f"_acme-challenge.{host}"


def query_txt(name: str) -> list[str]:
    """dig 查询 TXT，返回去引号的值列表。"""
    try:
        proc = subprocess.run(
            ["dig", "+short", "TXT", name],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"(dig error: {exc})"]
    if proc.returncode != 0 and not proc.stdout.strip():
        return []
    values: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # dig 输出形如 "v=..." 或 "\"v=...\""
        values.append(line.strip('"').strip())
    return values


def check_certificate(cert: CertificateConfig) -> list[tuple[str, str, list[str]]]:
    """返回 [(issue_domain, challenge_host, txt_values), ...]"""
    rows: list[tuple[str, str, list[str]]] = []
    for domain in cert.issue_domains:
        host = acme_challenge_host(domain)
        rows.append((domain, host, query_txt(host)))
    return rows


def print_certificate_checks(cert_name: str, cert: CertificateConfig) -> None:
    print(f"--- {cert_name} ({primary_issue_domain(cert.issue_domains)}) ---")
    for issue_domain, host, values in check_certificate(cert):
        if values:
            joined = " | ".join(values)
            print(f"  {host}: {joined}")
        else:
            print(f"  {host}: (no TXT)")


def print_all_checks(config_path: str | Path, cert_name: str | None = None) -> None:
    config = load_config(config_path)
    for cert in config.certificates:
        if cert_name and cert.name != cert_name:
            continue
        print_certificate_checks(cert.name, cert)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m qiniu_cert.dns_check <config.yaml> [cert-name]", file=sys.stderr)
        return 2
    cert_name = sys.argv[2] if len(sys.argv) > 2 else None
    print_all_checks(sys.argv[1], cert_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
