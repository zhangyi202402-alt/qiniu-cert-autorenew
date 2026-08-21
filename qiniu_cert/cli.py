"""命令行入口：部署、探活、旧证清理、批量 TLS 探活。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from qiniu_cert.cert_utils import DeployError, probe_force_https, tls_probe
from qiniu_cert.config import AppConfig, load_config
from qiniu_cert.deploy import DeployService


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _alert_deploy_failure(
    config: AppConfig,
    message: str,
    config_path: str | Path = "config.yaml",
) -> None:
    root = Path(__file__).resolve().parent.parent
    alert_sh = root / "scripts" / "alert.sh"
    if not alert_sh.is_file():
        return
    env = os.environ.copy()
    if config.notify_webhook and not env.get("NOTIFY_WEBHOOK"):
        env["NOTIFY_WEBHOOK"] = config.notify_webhook
    if config.notify_provider:
        env["NOTIFY_PROVIDER"] = config.notify_provider
    env["QINIU_CERT_CONFIG"] = str(Path(config_path).resolve())
    subprocess.run(["bash", str(alert_sh), message], check=False, env=env)


def cmd_deploy(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    service = DeployService(config)
    try:
        cert_id = service.deploy_from_files(
            issue_domain=args.domain,
            key_path=Path(args.key),
            fullchain_path=Path(args.fullchain),
        )
        print(f"deploy ok certID={cert_id}")
        return 0
    except DeployError as exc:
        print(f"deploy failed: {exc}", file=sys.stderr)
        _alert_deploy_failure(config, f"deploy failed ({args.domain}): {exc}", args.config)
        return 1


def cmd_cleanup(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    service = DeployService(config)
    deleted = service.cleanup_old_certs()
    print(json.dumps({"deleted": deleted}, indent=2))
    return 0


def cmd_tls_probe(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    min_days = args.min_days if args.min_days is not None else config.min_valid_days
    check_force = args.check_force_https
    if args.respect_config:
        from qiniu_cert.config import find_cert_by_cdn_domain

        cert = find_cert_by_cdn_domain(config, args.domain)
        check_force = cert.https.force_https if cert else False

    ok, msg = tls_probe(args.domain, min_valid_days=min_days)
    print(f"TLS: {ok} {msg}")
    if check_force:
        fh_ok, fh_msg = probe_force_https(args.domain)
        print(f"forceHttps: {fh_ok} {fh_msg}")
        ok = ok and fh_ok
    return 0 if ok else 1


def cmd_tls_probe_all(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    root = Path(__file__).resolve().parent.parent
    failed = 0
    from qiniu_cert.config import TargetAliyunClb, TargetQiniuCdn, iter_targets

    for cert in config.certificates:
        hosts: list[tuple[str, bool]] = []  # (host, check_force)
        for t in iter_targets(cert):
            if isinstance(t, TargetQiniuCdn):
                for d in t.domains:
                    hosts.append((d, t.https.force_https))
            elif isinstance(t, TargetAliyunClb):
                primary = t.probe_host or cert.issue_domains[0]
                hosts.append((primary, False))
                for d in t.domain_extensions:
                    hosts.append((d, False))
        if not hosts and cert.qiniu_cdn_domains:
            for d in cert.qiniu_cdn_domains:
                hosts.append((d, cert.https.force_https))

        for domain, check_force in hosts:
            ok, msg = tls_probe(domain, min_valid_days=config.min_valid_days)
            force_line = ""
            if check_force:
                fh_ok, fh_msg = probe_force_https(domain)
                force_line = f" forceHttps={fh_ok} {fh_msg}"
                ok = ok and fh_ok
            print(f"{domain}: TLS={ok} {msg}{force_line}")
            if not ok:
                failed = 1
                subprocess.run(
                    ["bash", str(root / "scripts" / "alert.sh"), f"TLS probe failed: {domain}"],
                    check=False,
                )
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description="CDN/CLB HTTPS 证书自动续签 CLI")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dep = sub.add_parser("deploy", help="上传并绑定证书到配置中的部署目标")
    p_dep.add_argument("-d", "--domain", required=True, help="ACME 签发主域名（匹配 config）")
    p_dep.add_argument("--key", required=True, help="私钥 PEM 路径")
    p_dep.add_argument("--fullchain", required=True, help="fullchain PEM 路径")
    p_dep.set_defaults(func=cmd_deploy)

    p_clean = sub.add_parser("cleanup", help="清理已到期的旧证书")
    p_clean.set_defaults(func=cmd_cleanup)

    p_tls = sub.add_parser("tls-probe", help="单域名 TLS 健康检查")
    p_tls.add_argument("domain", help="CDN/业务域名")
    p_tls.add_argument("--min-days", type=int, default=None, help="最少剩余有效天数（默认读 config）")
    p_tls.add_argument("--check-force-https", action="store_true", help="强制检查 HTTP→HTTPS")
    p_tls.add_argument(
        "--respect-config",
        action="store_true",
        help="按 config 中该域名的 force_https 决定是否检查跳转",
    )
    p_tls.set_defaults(func=cmd_tls_probe)

    p_all = sub.add_parser("tls-probe-all", help="探活 config 中全部部署域名")
    p_all.set_defaults(func=cmd_tls_probe_all)

    args = parser.parse_args()
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
