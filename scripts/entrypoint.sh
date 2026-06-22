#!/usr/bin/env bash
# Docker 容器入口：安装 acme.sh 后执行 command（supercronic 等）。
set -euo pipefail

export ACME_INSTALL_FORCE=1
# shellcheck source=bootstrap.sh
source "$(dirname "$0")/bootstrap.sh"

ln -sf "${ROOT}/scripts/qiniu_wrapper.sh" "${ACME_HOME}/deploy/qiniu_wrapper.sh"
bash "$(dirname "$0")/acme-install.sh"

exec "$@"
