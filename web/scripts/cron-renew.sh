#!/usr/bin/env bash
# 手动触发续签扫描（与 supercronic 任务等价）。
set -euo pipefail
cd "$(dirname "$0")/.."
exec python -m app.jobs.renew_all
