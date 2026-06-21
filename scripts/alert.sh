#!/usr/bin/env bash
# 告警通知：支持钉钉、飞书 webhook；无 webhook 时输出到 stderr。
#
# 用法: bash scripts/alert.sh "告警正文"
# 凭据优先级:
#   1. 环境变量 DINGTALK_WEBHOOK / FEISHU_WEBHOOK / NOTIFY_WEBHOOK
#   2. config.yaml 中 notify.webhook（支持 ${ENV} 展开）
set -euo pipefail

MSG="${1:-acme-qiniu alert}"
CONFIG="${QINIU_CERT_CONFIG:-/opt/qiniu-cert/config.yaml}"

TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
HOST="$(hostname -s 2>/dev/null || echo unknown)"
FULL_TEXT="[qiniu-cert] ${TS} ${HOST}\n${MSG}"

# 从环境变量或 config 解析 webhook 与 provider（dingtalk | feishu | auto）
read -r WEBHOOK PROVIDER < <(python3 - <<PY
import os, re, sys
from pathlib import Path

config_path = os.environ.get("QINIU_CERT_CONFIG", "/opt/qiniu-cert/config.yaml")
webhook = (
    os.environ.get("NOTIFY_WEBHOOK", "")
    or os.environ.get("DINGTALK_WEBHOOK", "")
    or os.environ.get("FEISHU_WEBHOOK", "")
)
provider = os.environ.get("NOTIFY_PROVIDER", "auto")

if not webhook and Path(config_path).is_file():
    import yaml
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    notify = cfg.get("notify", {}) or {}
    provider = notify.get("provider", provider) or "auto"
    w = notify.get("webhook", "") or ""
    m = re.match(r"\$\{([^}]+)\}", w or "")
    if m:
        webhook = os.environ.get(m.group(1), "")
    else:
        webhook = w

print(webhook)
print(provider)
PY
)

if [[ -n "${WEBHOOK}" ]]; then
  payload=$(python3 - <<PY
import json, os
webhook = """${WEBHOOK}"""
provider = """${PROVIDER}"""
text = """${FULL_TEXT}"""
if provider == "auto":
    provider = "dingtalk" if "oapi.dingtalk.com" in webhook else "feishu"
if provider == "dingtalk":
    body = {"msgtype": "text", "text": {"content": text}}
else:
    body = {"msg_type": "text", "content": {"text": text}}
print(json.dumps(body))
PY
)
  if curl -fsS -X POST "${WEBHOOK}" \
    -H 'Content-Type: application/json' \
    -d "${payload}" >/dev/null; then
    exit 0
  fi
  echo "[ALERT] webhook POST failed: ${MSG}" >&2
  exit 0
fi

echo "[ALERT] ${MSG}" >&2
exit 0
