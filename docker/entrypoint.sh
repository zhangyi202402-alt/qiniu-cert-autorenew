#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/acme /data/state /data/log
export PATH="/data/acme:${PATH}"
export HOME=/data/acme
export ACME_HOME=/data/acme
export PYTHONPATH="/app${PYTHONPATH:+:${PYTHONPATH}}"

/app/docker/install-acme.sh
/app/docker/install-hook.sh

exec "$@"
