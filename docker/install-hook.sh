#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${ACME_HOME}/deploy"
cp /app/scripts/qiniu_wrapper.sh "${ACME_HOME}/deploy/qiniu_wrapper.sh"
chmod +x "${ACME_HOME}/deploy/qiniu_wrapper.sh"
