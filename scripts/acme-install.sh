#!/usr/bin/env bash
# 安装 acme.sh 到 .local/acme 并设置默认 CA。
set -euo pipefail

# shellcheck source=bootstrap.sh
source "$(dirname "$0")/bootstrap.sh"

CONFIG="${QINIU_CERT_CONFIG}"
PYTHON="${QINIU_CERT_PYTHON}"

read -r ACME_EMAIL ACME_CA < <("${PYTHON}" - <<PY
from qiniu_cert.config import load_config
c = load_config("${CONFIG}")
print(c.acme.email, c.acme.ca)
PY
)

ACME_GIT_REPO="${ACME_GIT_REPO:-https://github.com/acmesh-official/acme.sh.git}"

if [[ -x "${ACME_HOME}/acme.sh" ]]; then
  echo "acme.sh already installed at ${ACME_HOME}"
else
  echo "Installing acme.sh from ${ACME_GIT_REPO} ..."
  CLONE_DIR="$(mktemp -d)"
  git clone --depth 1 "${ACME_GIT_REPO}" "${CLONE_DIR}/acme.sh"
  INSTALL_FLAGS=(--install -m "${ACME_EMAIL}" --home "${ACME_HOME}")
  if [[ "${ACME_INSTALL_FORCE:-}" == "1" ]]; then
    INSTALL_FLAGS+=(--force)
  fi
  (
    cd "${CLONE_DIR}/acme.sh"
    HOME="${ACME_HOME}" ./acme.sh "${INSTALL_FLAGS[@]}"
  )
  rm -rf "${CLONE_DIR}"
fi

export HOME="${ACME_HOME}"
"${ACME_HOME}/acme.sh" --home "${ACME_HOME}" --set-default-ca --server "${ACME_CA}"
