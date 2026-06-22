#!/bin/bash
# acme.sh 部署钩子：续签成功后由 acme 调用，将证书上传到七牛并绑定 CDN 域名。
#
# setup.sh 会 ln -sf 到 .local/acme/deploy/；首次 deploy 写入 Le_DeployHook。
set -euo pipefail

_qiniu_script_dir() {
  local src="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  while [[ -L "${src}" ]]; do
    local dir
    dir="$(cd "$(dirname "${src}")" && pwd)"
    src="$(readlink "${src}")"
    [[ "${src}" != /* ]] && src="${dir}/${src}"
  done
  cd "$(dirname "${src}")" && pwd
}

qiniu_wrapper_deploy() {
  _cdomain="${1:?}"
  _ckey="${2:?}"
  _ccert="${3:?}"
  _cca="${4:?}"
  _cfullchain="${5:?}"

  local script_dir root config python
  script_dir="$(_qiniu_script_dir)"
  root="$(cd "${script_dir}/.." && pwd)"
  config="${QINIU_CERT_CONFIG:-${root}/config.yaml}"
  python="${QINIU_CERT_PYTHON:-${root}/.venv/bin/python}"
  if [[ ! -x "${python}" ]]; then
    python="${QINIU_CERT_PYTHON:-python3}"
  fi

  export PYTHONPATH="${root}${PYTHONPATH:+:${PYTHONPATH}}"

  if ! "${python}" -m qiniu_cert.cli -c "${config}" deploy \
    -d "${_cdomain}" \
    --key "${_ckey}" \
    --fullchain "${_cfullchain}"; then
    return 1
  fi
}
