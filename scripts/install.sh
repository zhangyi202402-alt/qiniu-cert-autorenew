#!/usr/bin/env bash
# 在 clone 目录创建 venv 并安装依赖。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "${ROOT}/config.yaml" ]]; then
  cp "${ROOT}/config.example.yaml" "${ROOT}/config.yaml"
  echo "Created ${ROOT}/config.yaml — edit before use"
fi

if [[ -d "${ROOT}/.venv" ]]; then
  "${ROOT}/.venv/bin/pip" install -q -r "${ROOT}/requirements.txt"
else
  python3 -m venv "${ROOT}/.venv"
  "${ROOT}/.venv/bin/pip" install -q -r "${ROOT}/requirements.txt"
fi

chmod +x "${ROOT}/scripts/"*.sh

echo "Ready in ${ROOT}"
echo "Configure .env / config.yaml, then run:"
echo "  bash scripts/setup.sh"
echo "  bash scripts/install-cron.sh"
