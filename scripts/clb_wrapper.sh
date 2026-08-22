#!/bin/bash
# acme.sh 部署钩子：续签成功后将证书部署到配置中的目标（七牛 CDN 和/或阿里云 CLB）。
# 与 qiniu_wrapper 相同入口；DeployRouter 按 config targets 分流。
set -euo pipefail

_clb_script_dir() {
  local src="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  while [[ -L "${src}" ]]; do
    local dir
    dir="$(cd "$(dirname "${src}")" && pwd)"
    src="$(readlink "${src}")"
    [[ "${src}" != /* ]] && src="${dir}/${src}"
  done
  cd "$(dirname "${src}")" && pwd
}

clb_wrapper_deploy() {
  _cdomain="${1:?}"
  _ckey="${2:?}"
  _ccert="${3:?}"
  _cca="${4:?}"
  _cfullchain="${5:?}"

  local script_dir root config python
  script_dir="$(_clb_script_dir)"
  root="$(cd "${script_dir}/.." && pwd)"
  config="${QINIU_CERT_CONFIG:-${root}/config.yaml}"
  python="${QINIU_CERT_PYTHON:-${root}/.venv/bin/python}"
  if [[ ! -x "${python}" ]]; then
    python="${QINIU_CERT_PYTHON:-python3}"
  fi

  export PYTHONPATH="${root}${PYTHONPATH:+:${PYTHONPATH}}"

  # config 中 enabled: false 时跳过换绑（不触发探活）
  if "${python}" -c "
from qiniu_cert.config import load_config, find_cert_by_issue_domain
import sys
c = load_config(sys.argv[1])
cert = find_cert_by_issue_domain(c, sys.argv[2])
raise SystemExit(0 if (cert is not None and not cert.enabled) else 1)
" "${config}" "${_cdomain}"; then
    echo "clb_wrapper: certificate disabled, skip deploy for ${_cdomain}"
    return 0
  fi

  if ! "${python}" -m qiniu_cert.cli -c "${config}" deploy \
    -d "${_cdomain}" \
    --key "${_ckey}" \
    --fullchain "${_cfullchain}"; then
    return 1
  fi
}
