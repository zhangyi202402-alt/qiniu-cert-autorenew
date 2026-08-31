FROM docker.1ms.run/python:3.12-slim-bookworm

ARG SUPERCRONIC_VERSION=v0.2.33
ARG TARGETARCH
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG http_proxy
ARG https_proxy
ARG NO_PROXY
ARG no_proxy

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${http_proxy} \
    https_proxy=${https_proxy} \
    NO_PROXY=${NO_PROXY} \
    no_proxy=${no_proxy}

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
    && curl -fsSL "https://ghfast.top/https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${SUPERCRONIC_ARCH}" \
        -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY qiniu_cert/ qiniu_cert/
COPY scripts/ scripts/

RUN chmod +x /app/scripts/*.sh \
    && unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy || true

# 运行时不走构建代理
ENV HTTP_PROXY= \
    HTTPS_PROXY= \
    http_proxy= \
    https_proxy= \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    QINIU_CERT_ROOT=/app \
    QINIU_CERT_CONFIG=/app/config.yaml \
    QINIU_CERT_PYTHON=python3 \
    ACME_GIT_REPO=https://ghfast.top/https://github.com/acmesh-official/acme.sh.git

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
