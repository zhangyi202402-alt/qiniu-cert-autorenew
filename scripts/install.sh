#!/usr/bin/env bash
# 一键安装：将项目同步到 /opt/qiniu-cert，创建 venv 并安装依赖。
#
# 安装后需配置 QINIU_AK/SK、DNS 凭据，再运行 setup-acme.sh。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${QINIU_CERT_INSTALL_DIR:-/opt/qiniu-cert}"

sudo mkdir -p "${INSTALL_DIR}"
sudo rsync -a --exclude '__pycache__' --exclude '.pytest_cache' \
  "${ROOT}/" "${INSTALL_DIR}/"

if [[ ! -f "${INSTALL_DIR}/config.yaml" ]]; then
  sudo cp "${INSTALL_DIR}/config.example.yaml" "${INSTALL_DIR}/config.yaml"
  echo "Created ${INSTALL_DIR}/config.yaml — edit before use"
fi

if [[ -d "${INSTALL_DIR}/.venv" ]]; then
  sudo "${INSTALL_DIR}/.venv/bin/pip" install -q -r "${INSTALL_DIR}/requirements.txt"
else
  sudo python3 -m venv "${INSTALL_DIR}/.venv"
  sudo "${INSTALL_DIR}/.venv/bin/pip" install -q -r "${INSTALL_DIR}/requirements.txt"
fi

sudo chmod +x "${INSTALL_DIR}/scripts/"*.sh

echo "Installed to ${INSTALL_DIR}"
echo "Set QINIU_AK, QINIU_SK, DNS credentials, then run:"
echo "  export QINIU_CERT_PYTHON=${INSTALL_DIR}/.venv/bin/python"
echo "  sudo QINIU_CERT_CONFIG=${INSTALL_DIR}/config.yaml ${INSTALL_DIR}/scripts/setup-acme.sh"
