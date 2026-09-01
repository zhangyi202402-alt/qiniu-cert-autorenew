#!/usr/bin/env bash
# 首次安装：acme.sh → 全部证书签发 + deploy（裸机与 Docker 共用）。
#
# 前置：config.yaml 已配置，DNS 凭据在 .env 或环境中。
set -euo pipefail

# shellcheck source=bootstrap.sh
source "$(dirname "$0")/bootstrap.sh"

if [[ ! -f "${QINIU_CERT_CONFIG}" ]]; then
  echo "Copy config.example.yaml to ${QINIU_CERT_CONFIG} and set credentials"
  exit 1
fi

ln -sf "${ROOT}/scripts/qiniu_wrapper.sh" "${ACME_HOME}/deploy/qiniu_wrapper.sh"
ln -sf "${ROOT}/scripts/clb_wrapper.sh" "${ACME_HOME}/deploy/clb_wrapper.sh"
ln -sf "${ROOT}/scripts/cdn_wrapper.sh" "${ACME_HOME}/deploy/cdn_wrapper.sh"

bash "$(dirname "$0")/acme-install.sh"
bash "$(dirname "$0")/acme-issue-all.sh"
"${PYTHON}" -m qiniu_cert.acme_plan sync-renew-days "${CONFIG}" "${ACME_HOME}"

if [[ -n "${QINIU_CERT_ROOT:-}" ]]; then
  echo "Setup complete."
else
  echo "Done. Next: bash scripts/install-cron.sh"
fi
