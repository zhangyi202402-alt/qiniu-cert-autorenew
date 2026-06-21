#!/usr/bin/env bash
# 首次启动时从 Gitee 安装 acme.sh 到 /data/acme（由 volume 持久化）
set -euo pipefail

if [[ -x "${ACME_HOME}/acme.sh" ]]; then
  exit 0
fi

EMAIL="$(python3 - <<'PY'
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path("/app/config.yaml").read_text(encoding="utf-8"))
print(cfg.get("acme", {}).get("email", "ops@example.com"))
PY
)"

REPO="${ACME_GIT_REPO:-https://gitee.com/neilpang/acme.sh.git}"
CLONE_DIR="$(mktemp -d)"

echo "Installing acme.sh from ${REPO} ..."
git clone --depth 1 "${REPO}" "${CLONE_DIR}/acme.sh"
(
  cd "${CLONE_DIR}/acme.sh"
  ./acme.sh --install --force -m "${EMAIL}" --home "${ACME_HOME}"
)
rm -rf "${CLONE_DIR}"
echo "acme.sh installed at ${ACME_HOME}"
