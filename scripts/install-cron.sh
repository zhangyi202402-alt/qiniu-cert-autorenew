#!/usr/bin/env bash
# 安装 crontab：每日 acme 续签 + TLS 探活；失败时写日志并告警。
#
# acme cron: 每天 00:08，失败则调用 alert.sh（禁止重定向到 /dev/null）
# TLS cron:  每天 08:15，探活全部 CDN 域名并尝试 cleanup 旧证
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${QINIU_CERT_INSTALL_DIR:-/opt/qiniu-cert}"
LOG_FILE="${QINIU_CERT_LOG:-/var/log/acme-qiniu.log}"
ACME_HOME="${HOME}/.acme.sh"

mkdir -p "$(dirname "${LOG_FILE}")"

CRON_ACME="8 0 * * * \"${ACME_HOME}\"/acme.sh --cron --home \"${ACME_HOME}\" >> \"${LOG_FILE}\" 2>&1 || ${INSTALL_DIR}/scripts/alert.sh \"acme cron failed\""
CRON_TLS="15 8 * * * ${INSTALL_DIR}/scripts/tls-probe-cron.sh >> \"${LOG_FILE}\" 2>&1"

# 移除旧条目后追加，避免重复安装
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'acme.sh --cron' | grep -v 'tls-probe-cron.sh' > "${TMP}" || true
{
  cat "${TMP}"
  echo "${CRON_ACME}"
  echo "${CRON_TLS}"
} | crontab -
rm -f "${TMP}"

echo "Installed crontab:"
crontab -l
