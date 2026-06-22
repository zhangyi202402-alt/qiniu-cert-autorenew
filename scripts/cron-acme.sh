#!/usr/bin/env bash
# 定时：acme 续签 + deploy（裸机 crontab 与 Docker supercronic 共用）。
set -euo pipefail

# shellcheck source=bootstrap.sh
source "$(dirname "$0")/bootstrap.sh"

if [[ ! -x "${ACME_HOME}/acme.sh" ]]; then
  echo "acme.sh 未安装（${ACME_HOME}/acme.sh 不存在）。" >&2
  echo "请先执行: bash scripts/setup.sh" >&2
  exit 1
fi

if [[ "$("${QINIU_CERT_PYTHON}" -c "from qiniu_cert.config import load_config; print(1 if load_config('${QINIU_CERT_CONFIG}').acme.no_ari else 0)")" == "1" ]]; then
  export NO_ARI=1
fi

if ! "${ACME_HOME}/acme.sh" --cron --home "${ACME_HOME}" >> "${LOG_FILE}" 2>&1; then
  bash "${ROOT}/scripts/alert.sh" "acme cron failed"
  exit 1
fi
