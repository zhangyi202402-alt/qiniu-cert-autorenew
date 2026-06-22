#!/usr/bin/env bash
# 统一项目数据目录：.local/acme、.local/state、.local/log（Docker 与裸机共用）
#
# 用法:
#   source "$(dirname "$0")/project-env.sh"
# 容器内可设: QINIU_CERT_ROOT=/app
set -euo pipefail

if [[ -n "${QINIU_CERT_ROOT:-}" ]]; then
  ROOT="${QINIU_CERT_ROOT}"
else
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

LOCAL_DIR="${ROOT}/.local"
ACME_HOME="${LOCAL_DIR}/acme"
LOG_DIR="${LOCAL_DIR}/log"
LOG_FILE="${QINIU_CERT_LOG:-${LOG_DIR}/acme-qiniu.log}"

mkdir -p "${ACME_HOME}" "${ACME_HOME}/deploy" "${LOCAL_DIR}/state" "${LOG_DIR}"

export ROOT LOCAL_DIR ACME_HOME LOG_DIR LOG_FILE
export PATH="${ACME_HOME}:${PATH}"
