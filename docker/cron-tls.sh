#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH=/app
export QINIU_CERT_CONFIG="${QINIU_CERT_CONFIG:-/app/config.yaml}"

LOG="/data/log/acme-qiniu.log"
mkdir -p "$(dirname "${LOG}")"

if ! /app/scripts/tls-probe-cron.sh >> "${LOG}" 2>&1; then
  exit 1
fi
