"""命令行入口：部署、探活、旧证清理。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from qiniu_cert.cert_utils import DeployError
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
    """部署失败时调用 webhook 告警（钉钉/飞书）。"""
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
    """将 key/fullchain 部署到七牛（acme.sh hook 或手动调用）。"""
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
    """删除 state 中已到期的 previous_cert_id。"""
    config = load_config(args.config)
    service = DeployService(config)
    deleted = service.cleanup_old_certs()
    print(json.dumps({"deleted": deleted}, indent=2))
    return 0


def cmd_tls_probe(args: argparse.Namespace) -> int:
    """独立 TLS / forceHttps 探活（供 cron 或手动检查）。"""
    from qiniu_cert.cert_utils import probe_force_https, tls_probe

    ok, msg = tls_probe(args.domain, min_valid_days=args.min_days)
    print(f"TLS: {ok} {msg}")
    if args.check_force_https:
        fh_ok, fh_msg = probe_force_https(args.domain)
        print(f"forceHttps: {fh_ok} {fh_msg}")
        ok = ok and fh_ok
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="七牛 CDN HTTPS 证书自动续签 CLI")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dep = sub.add_parser("deploy", help="上传并绑定证书到七牛 CDN")
    p_dep.add_argument("-d", "--domain", required=True, help="ACME 签发主域名（匹配 config）")
    p_dep.add_argument("--key", required=True, help="私钥 PEM 路径")
    p_dep.add_argument("--fullchain", required=True, help="fullchain PEM 路径")
    p_dep.set_defaults(func=cmd_deploy)

    p_clean = sub.add_parser("cleanup", help="清理已到期的旧证书")
    p_clean.set_defaults(func=cmd_cleanup)

    p_tls = sub.add_parser("tls-probe", help="TLS 健康检查")
    p_tls.add_argument("domain", help="CDN 域名")
    p_tls.add_argument("--min-days", type=int, default=30, help="证书最少剩余有效天数")
    p_tls.add_argument("--check-force-https", action="store_true", help="同时检查 HTTP→HTTPS 跳转")
    p_tls.set_defaults(func=cmd_tls_probe)

    args = parser.parse_args()
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
