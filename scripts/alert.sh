#!/usr/bin/env bash
# 告警通知：支持钉钉、飞书 webhook；无 webhook 时输出到 stderr。
#
# 用法: bash scripts/alert.sh "告警正文"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=load-env.sh
source "$(dirname "$0")/load-env.sh"

MSG="${1:-acme-qiniu alert}"
CONFIG="${QINIU_CERT_CONFIG:-${ROOT}/config.yaml}"
PYTHON="${QINIU_CERT_PYTHON:-${ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="${QINIU_CERT_PYTHON:-python3}"
fi
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
HOST="$(hostname -s 2>/dev/null || echo unknown)"
FULL_TEXT="[qiniu-cert] ${TS} ${HOST}\n${MSG}"

read -r WEBHOOK PROVIDER < <("${PYTHON}" -m qiniu_cert.notify "${CONFIG}")

if [[ -n "${WEBHOOK}" ]]; then
  payload=$("${PYTHON}" - <<PY
import json
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
