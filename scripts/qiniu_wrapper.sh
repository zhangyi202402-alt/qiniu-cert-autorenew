#!/usr/bin/env bash
# acme.sh 部署钩子：续签成功后由 acme 调用，将证书上传到七牛并绑定 CDN 域名。
#
# 安装方式：
#   cp scripts/qiniu_wrapper.sh ~/.acme.sh/deploy/qiniu_wrapper.sh
#   acme.sh --deploy -d example.com --deploy-hook qiniu_wrapper
#
# 首次 deploy 会在域名 conf 中写入 Le_DeployHook，此后 cron 续签会自动触发。
set -euo pipefail

qiniu_wrapper_deploy() {
  # acme.sh 传入：域名、私钥、证书、CA、fullchain 路径
  _cdomain="${1:?}"
  _ckey="${2:?}"
  _ccert="${3:?}"
  _cca="${4:?}"
  _cfullchain="${5:?}"

  local install_dir="${QINIU_CERT_INSTALL_DIR:-/opt/qiniu-cert}"
  local config="${QINIU_CERT_CONFIG:-${install_dir}/config.yaml}"
  local python="${QINIU_CERT_PYTHON:-${install_dir}/.venv/bin/python}"
  if [[ ! -x "${python}" ]]; then
    python="${QINIU_CERT_PYTHON:-python3}"
  fi

  # 确保能找到 qiniu_cert 包（未 pip install 时依赖安装目录）
  export PYTHONPATH="${install_dir}${PYTHONPATH:+:${PYTHONPATH}}"

  if ! "${python}" -m qiniu_cert.cli -c "${config}" deploy \
    -d "${_cdomain}" \
    --key "${_ckey}" \
    --fullchain "${_cfullchain}"; then
    return 1
  fi
}
