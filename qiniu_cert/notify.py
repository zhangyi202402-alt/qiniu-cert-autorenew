"""告警 webhook 解析（供 alert.sh 使用）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from qiniu_cert.config import load_config


def resolve_notify(config_path: str | Path) -> tuple[str, str]:
    """返回 (webhook_url, provider)；webhook 为空表示未配置。"""
    webhook = (
        os.environ.get("NOTIFY_WEBHOOK", "")
        or os.environ.get("DINGTALK_WEBHOOK", "")
        or os.environ.get("FEISHU_WEBHOOK", "")
    )
    provider = os.environ.get("NOTIFY_PROVIDER", "")

    if Path(config_path).is_file():
        cfg = load_config(config_path)
        if not webhook:
            webhook = cfg.notify_webhook
        if not provider and cfg.notify_provider:
            provider = cfg.notify_provider

    if not provider:
        provider = "auto"

    return webhook, provider


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: notify <config.yaml>", file=sys.stderr)
        return 2
    webhook, provider = resolve_notify(sys.argv[1])
    print(webhook)
    print(provider)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
