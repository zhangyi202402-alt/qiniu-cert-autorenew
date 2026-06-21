#!/usr/bin/env bash
# Phase 1：安装 acme.sh、签发 staging 证书、首次 deploy 并持久化 Le_DeployHook。
#
# 前置：config.yaml 已配置，且 DNS API 环境变量已 export。
set -euo pipefail

# 加载项目根 .env（若存在）
# shellcheck source=load-env.sh
source "$(dirname "$0")/load-env.sh"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${QINIU_CERT_CONFIG:-${ROOT}/config.yaml}"
INSTALL_DIR="${QINIU_CERT_INSTALL_DIR:-/opt/qiniu-cert}"
PYTHON="${QINIU_CERT_PYTHON:-${ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="${QINIU_CERT_PYTHON:-python3}"
fi

if [[ ! -f "${CONFIG}" ]]; then
  echo "Copy config.example.yaml to ${CONFIG} and set credentials"
  exit 1
fi

# 从 config 读取 ACME 与全部 issue_domains（支持通配符 -d）
eval "$("${PYTHON}" - <<PY
import shlex
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path("${CONFIG}").read_text())
acme = cfg.get("acme", {})
print(f'ACME_EMAIL="{acme.get("email", "ops@example.com")}"')
print(f'ACME_CA="{acme.get("ca", "letsencrypt_test")}"')
cert = cfg["certificates"][0]
domains = cert["issue_domains"]
print(f'PRIMARY_DOMAIN="{domains[0]}"')
print(f'DNS_PROVIDER="{cert["dns_provider"]}"')
provider = cert["dns_provider"]
dns_hook = provider if provider.startswith("dns_") else f"dns_{provider}"
print(f'DNS_HOOK="{dns_hook}"')
domain_args = " ".join(shlex.quote(f"-d {d}") for d in domains)
print(f'DOMAIN_ARGS={domain_args}')
PY
)"

ACME_HOME="${HOME}/.acme.sh"
ACME_GIT_REPO="${ACME_GIT_REPO:-https://gitee.com/neilpang/acme.sh.git}"

if [[ -x "${ACME_HOME}/acme.sh" ]]; then
  echo "acme.sh already installed at ${ACME_HOME}"
else
  echo "Installing acme.sh from ${ACME_GIT_REPO} ..."
  CLONE_DIR="$(mktemp -d)"
  git clone --depth 1 "${ACME_GIT_REPO}" "${CLONE_DIR}/acme.sh"
  # 须在克隆目录内执行 --install（与官方文档一致：cd acme.sh && ./acme.sh --install）
  (
    cd "${CLONE_DIR}/acme.sh"
    ./acme.sh --install -m "${ACME_EMAIL}" --home "${ACME_HOME}"
  )
  rm -rf "${CLONE_DIR}"
fi

export PATH="${ACME_HOME}:${PATH}"
acme.sh --set-default-ca --server "${ACME_CA}"

# 导出 config.dns_env 中声明的 DNS 凭据环境变量
eval "$("${PYTHON}" - <<PY
import os, yaml
from pathlib import Path
cfg = yaml.safe_load(Path("${CONFIG}").read_text())
for cert in cfg.get("certificates", []):
    for env_name in cert.get("dns_env", {}).values():
        val = os.environ.get(env_name, "")
        if val:
            print(f'export {env_name}="{val}"')
PY
)"

HOOK_SRC="${ROOT}/scripts/qiniu_wrapper.sh"
HOOK_DST="${ACME_HOME}/deploy/qiniu_wrapper.sh"
cp "${HOOK_SRC}" "${HOOK_DST}"
chmod +x "${HOOK_DST}"

export QINIU_CERT_CONFIG="${CONFIG}"
export QINIU_CERT_INSTALL_DIR="${INSTALL_DIR}"

echo "Issue certificate (staging) for ${PRIMARY_DOMAIN}..."
acme.sh --issue --dns "${DNS_HOOK}" ${DOMAIN_ARGS} --keylength ec-256

echo "Deploy to Qiniu via wrapper..."
# 必须执行 deploy，否则 cron 续签后不会自动换绑七牛证书
acme.sh --deploy -d "${PRIMARY_DOMAIN}" --deploy-hook qiniu_wrapper

echo "Verify Le_DeployHook persisted:"
grep Le_DeployHook "${ACME_HOME}/${PRIMARY_DOMAIN}_ecc/${PRIMARY_DOMAIN}.conf" || true

echo "Done. Next: bash scripts/install-cron.sh"
