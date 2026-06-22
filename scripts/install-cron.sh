#!/usr/bin/env bash
# 安装 crontab：每日 acme 续签 + TLS 探活。
set -euo pipefail

# shellcheck source=bootstrap.sh
source "$(dirname "$0")/bootstrap.sh"

CRON_ACME="8 0 * * * cd \"${ROOT}\" && ${ROOT}/scripts/cron-acme.sh"
CRON_TLS="15 8 * * * cd \"${ROOT}\" && ${ROOT}/scripts/cron-tls.sh"

TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'scripts/cron-acme.sh' | grep -v 'scripts/cron-tls.sh' > "${TMP}" || true
{
  cat "${TMP}"
  echo "${CRON_ACME}"
  echo "${CRON_TLS}"
} | crontab -
rm -f "${TMP}"

echo "Installed crontab (ACME_HOME=${ACME_HOME}, LOG=${LOG_FILE}):"
crontab -l
