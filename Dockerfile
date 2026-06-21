FROM python:3.12-slim-bookworm

ARG SUPERCRONIC_VERSION=v0.2.33
ARG TARGETARCH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        dnsutils \
        git \
        openssl \
    && case "${TARGETARCH}" in \
        arm64) SUPERCRONIC_ARCH=arm64 ;; \
        amd64) SUPERCRONIC_ARCH=amd64 ;; \
        *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${SUPERCRONIC_ARCH}" \
        -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY qiniu_cert/ qiniu_cert/
COPY scripts/ scripts/
COPY docker/ docker/

RUN chmod +x /app/docker/*.sh /app/scripts/*.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    QINIU_CERT_INSTALL_DIR=/app \
    QINIU_CERT_CONFIG=/app/config.yaml \
    QINIU_CERT_PYTHON=python3 \
    HOME=/data/acme \
    ACME_HOME=/data/acme \
    ACME_GIT_REPO=https://gitee.com/neilpang/acme.sh.git

ENTRYPOINT ["/app/docker/entrypoint.sh"]
