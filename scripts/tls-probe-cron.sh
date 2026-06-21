#!/usr/bin/env bash
# Phase 3：对 config 中全部 CDN 域名做 TLS + forceHttps 探活，并清理到期旧证。
#
# 探活失败会调用 alert.sh；脚本 exit 1 供 cron 记录失败状态。
set -euo pipefail

# shellcheck source=load-env.sh
source "$(dirname "$0")/load-env.sh"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${QINIU_CERT_CONFIG:-${ROOT}/config.yaml}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

FAILED=0
while IFS= read -r domain; do
  [[ -z "${domain}" ]] && continue
  if ! python3 -m qiniu_cert.cli -c "${CONFIG}" tls-probe "${domain}" --check-force-https; then
    FAILED=1
    bash "${ROOT}/scripts/alert.sh" "TLS probe failed: ${domain}"
  fi
done < <(python3 - <<PY
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path("${CONFIG}").read_text())
for cert in cfg.get('certificates', []):
    for d in cert.get('qiniu_cdn_domains', []):
        print(d)
PY
)

# 顺带执行旧证清理（失败不阻断探活结果）
python3 -m qiniu_cert.cli -c "${CONFIG}" cleanup || true

exit "${FAILED}"
