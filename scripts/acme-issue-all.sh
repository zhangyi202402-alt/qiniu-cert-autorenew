#!/usr/bin/env bash
# 按 config.yaml 中全部 certificates 逐张签发并 deploy 到七牛。
set -euo pipefail

# shellcheck source=bootstrap.sh
source "$(dirname "$0")/bootstrap.sh"

CONFIG="${QINIU_CERT_CONFIG}"
PYTHON="${QINIU_CERT_PYTHON}"

export HOME="${ACME_HOME}"
export PATH="${ACME_HOME}:${PATH}"
export QINIU_CERT_CONFIG="${CONFIG}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

ln -sf "${ROOT}/scripts/qiniu_wrapper.sh" "${ACME_HOME}/deploy/qiniu_wrapper.sh"
ln -sf "${ROOT}/scripts/clb_wrapper.sh" "${ACME_HOME}/deploy/clb_wrapper.sh"

eval "$("${PYTHON}" -m qiniu_cert.acme_plan export-dns "${CONFIG}")"

ACME_DAYS="$("${PYTHON}" -c "from qiniu_cert.config import load_config; from qiniu_cert.acme_plan import acme_days_arg; print(acme_days_arg(load_config('${CONFIG}')))")"
if [[ "$("${PYTHON}" -c "from qiniu_cert.config import load_config; print(1 if load_config('${CONFIG}').acme.no_ari else 0)")" == "1" ]]; then
  export NO_ARI=1
fi

while IFS=$'\t' read -r name primary dns_hook domain_args key_type cert_dir deploy_hook; do
  echo "=== Certificate: ${name} (${primary}) hook=${deploy_hook} key=${key_type} ==="
  echo "--- DNS TXT before issue ---"
  "${PYTHON}" -m qiniu_cert.dns_check "${CONFIG}" "${name}"
  FORCE_ARGS=()
  if [[ "${ACME_FORCE:-}" == "1" ]]; then
    FORCE_ARGS=(--force)
  fi
  # shellcheck disable=SC2086
  if ! acme.sh --home "${ACME_HOME}" --issue --dns "${dns_hook}" ${domain_args} --keylength "${key_type}" --days "${ACME_DAYS}" "${FORCE_ARGS[@]}"; then
    echo "--- DNS TXT after failed issue ---"
    "${PYTHON}" -m qiniu_cert.dns_check "${CONFIG}" "${name}"
    exit 1
  fi
  echo "--- DNS TXT after issue ---"
  "${PYTHON}" -m qiniu_cert.dns_check "${CONFIG}" "${name}"
  acme.sh --home "${ACME_HOME}" --deploy -d "${primary}" --deploy-hook "${deploy_hook}"
  grep Le_DeployHook "${ACME_HOME}/${cert_dir}/${primary}.conf" || true
done < <("${PYTHON}" -m qiniu_cert.acme_plan list-certs "${CONFIG}")

echo "All certificates issued and deployed."
