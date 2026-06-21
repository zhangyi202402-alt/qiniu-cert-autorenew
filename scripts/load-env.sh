#!/usr/bin/env bash
# 若项目根目录存在 .env，则加载为环境变量（供各 scripts  source 使用）
set -euo pipefail

_load_env_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${_load_env_root}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${_load_env_root}/.env"
  set +a
fi
