#!/usr/bin/env bash
# Docker 入口：迁移 → 后台 cron → 前台 uvicorn（PID 1）
set -euo pipefail
cd /app/web
alembic upgrade head
supercronic /app/web/scripts/crontab.web &
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
