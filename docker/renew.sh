#!/usr/bin/env bash
# 手动执行一次 acme cron（续签 + deploy）
set -euo pipefail

export PATH="/data/acme:${PATH}"
export HOME=/data/acme

exec /app/docker/cron-acme.sh
