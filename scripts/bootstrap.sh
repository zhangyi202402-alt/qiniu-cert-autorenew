#!/usr/bin/env bash
# 各脚本共用：加载 .env、项目路径、Python 与 acme 环境。
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"

# shellcheck source=load-env.sh
source "${_SCRIPT_DIR}/load-env.sh"
# shellcheck source=project-env.sh
source "${_SCRIPT_DIR}/project-env.sh"

export QINIU_CERT_CONFIG="${QINIU_CERT_CONFIG:-${ROOT}/config.yaml}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

_PYTHON="${QINIU_CERT_PYTHON:-${ROOT}/.venv/bin/python}"
if [[ ! -x "${_PYTHON}" ]]; then
  _PYTHON="${QINIU_CERT_PYTHON:-python3}"
fi
export QINIU_CERT_PYTHON="${_PYTHON}"
export HOME="${ACME_HOME}"
