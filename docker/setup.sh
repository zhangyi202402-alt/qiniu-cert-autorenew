#!/usr/bin/env bash
# 首次：签发证书 + deploy 到七牛（持久化 Le_DeployHook）
set -euo pipefail

export PATH="/data/acme:${PATH}"
export HOME=/data/acme
export ACME_HOME=/data/acme
export PYTHONPATH=/app
export QINIU_CERT_CONFIG="${QINIU_CERT_CONFIG:-/app/config.yaml}"
export QINIU_CERT_INSTALL_DIR=/app
export QINIU_CERT_PYTHON=python3

eval "$(python3 - <<'PY'
import shlex
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path("/app/config.yaml").read_text(encoding="utf-8"))
acme = cfg.get("acme", {})
print(f'ACME_CA="{acme.get("ca", "letsencrypt")}"')
cert = cfg["certificates"][0]
domains = cert["issue_domains"]
print(f'PRIMARY_DOMAIN="{domains[0]}"')
provider = cert["dns_provider"]
dns_hook = provider if provider.startswith("dns_") else f"dns_{provider}"
print(f'DNS_HOOK="{dns_hook}"')
domain_args = " ".join(shlex.quote(f"-d {d}") for d in domains)
print(f'DOMAIN_ARGS={domain_args}')
PY
)"

/data/acme/acme.sh --set-default-ca --server "${ACME_CA}"

echo "Issue certificate for ${PRIMARY_DOMAIN} ..."
/data/acme/acme.sh --issue --dns "${DNS_HOOK}" ${DOMAIN_ARGS} --keylength ec-256

echo "Deploy to Qiniu ..."
/data/acme/acme.sh --deploy -d "${PRIMARY_DOMAIN}" --deploy-hook qiniu_wrapper

grep Le_DeployHook "${ACME_HOME}/${PRIMARY_DOMAIN}_ecc/${PRIMARY_DOMAIN}.conf" || true
echo "Setup complete."
