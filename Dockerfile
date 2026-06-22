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

RUN chmod +x /app/scripts/*.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    QINIU_CERT_ROOT=/app \
    QINIU_CERT_CONFIG=/app/config.yaml \
    QINIU_CERT_PYTHON=python3 \
    ACME_GIT_REPO=https://github.com/acmesh-official/acme.sh.git

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
