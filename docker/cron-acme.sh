#!/usr/bin/env bash
set -euo pipefail

export PATH="/data/acme:${PATH}"
export HOME=/data/acme
LOG="/data/log/acme-qiniu.log"

mkdir -p "$(dirname "${LOG}")"

if ! /data/acme/acme.sh --cron --home /data/acme >> "${LOG}" 2>&1; then
  /app/scripts/alert.sh "acme cron failed"
  exit 1
fi
