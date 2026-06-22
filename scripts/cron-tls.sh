#!/usr/bin/env bash
# 定时：TLS 探活 + 旧证清理（裸机 crontab 与 Docker supercronic 共用）。
set -euo pipefail

# shellcheck source=bootstrap.sh
source "$(dirname "$0")/bootstrap.sh"

_run_probe() {
  "${QINIU_CERT_PYTHON}" -m qiniu_cert.cli -c "${QINIU_CERT_CONFIG}" tls-probe-all
  PROBE_RC=$?
  "${QINIU_CERT_PYTHON}" -m qiniu_cert.cli -c "${QINIU_CERT_CONFIG}" cleanup || true
  return "${PROBE_RC}"
}

if ! _run_probe >> "${LOG_FILE}" 2>&1; then
  exit 1
fi
