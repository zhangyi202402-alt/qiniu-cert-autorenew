# SSL 证书 Web 控制台

基于 `qiniu_cert` 的轻量 Web：注册 / 登录、按用户配置云凭据、添加域名、DNS TXT 归属验证、自动签发并部署七牛 CDN、归属有效才续签。

## 与现有 CLI / Docker 签发的关系（重要）

| | 现有七牛/阿里 CLI | Web 控制台 |
|--|-------------------|------------|
| 代码 | `qiniu_cert/`、`scripts/`、根 `docker-compose.yml` | 仅 `web/` |
| 配置 | 根目录 `config.yaml` + `.env` | `web/.env` + MySQL |
| 证书目录 | `.local/acme/` | `.local/web/{user_id}/{cert_id}/acme/` |
| 定时 | `cron-acme.sh` / scheduler 容器 | `web` 内 supercronic |

Web **只读复用** `qiniu_cert` 与 `scripts/qiniu_wrapper.sh`，**不改写** CLI 逻辑。你现在的卡拉丁/七牛、阿里云 DNS、CLB 签发续签继续用原来的：

```bash
# 与以前完全相同
docker compose up -d scheduler
# 或
bash -c 'source scripts/bootstrap.sh && bash scripts/acme-issue-all.sh'
```

不要把 Web 的 MySQL / `.local/web` 当成 CLI 的配置源。

## 快速开始（Docker）

```bash
cd web
cp .env.example .env   # 填写 SECRET_KEY / WEB_MASTER_KEY
# 基础镜像走 docker.1ms.run（本机已有 python:3.12-slim-bookworm 缓存）
docker compose -f docker-compose.web.yml up -d --build
```

浏览器打开 http://127.0.0.1:8000

## 本地开发

```bash
# 需要 MySQL 5.7+，库名 qiniu_cert_web
cd web
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r ../requirements.txt
export PYTHONPATH="$(pwd)/..:$(pwd)"
export DATABASE_URL='mysql+pymysql://qcert:secret@127.0.0.1:3307/qiniu_cert_web?charset=utf8mb4'
export SECRET_KEY=dev
export WEB_MASTER_KEY="$(python -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## 用户流程

1. 注册 / 登录  
2. **凭证**：按云添加阿里云 / 腾讯云 / 七牛密钥（通用，可复用）  
3. **配置档**：组合 DNS 插件 + 凭证 + 部署类型（七牛 CDN 或阿里 CLB）  
4. **添加域名**：选配置档，填写签发域名与 CDN/CLB 目标 → `_qcert-verify` TXT 归属验证  
5. 验证通过后自动签发 / 部署；cron 每日复检归属，丢失则停止续签  

域名与部署目标在证书上（B1）；配置档不含具体域名。
