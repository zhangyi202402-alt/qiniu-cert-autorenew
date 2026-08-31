# SSL 证书 Web 控制台（v3）

基于 `qiniu_cert` 的 Web 控制台：**v3.0.0 起与 v2 CLI 不兼容**。版本说明见 [docs/VERSIONING.md](../docs/VERSIONING.md)，迁移见 [docs/MIGRATION-v3.md](../docs/MIGRATION-v3.md)。

## 与 v2 CLI 的关系

| | v2 CLI（`v2.0.0`，无 UI） | v3 Web（本目录） |
|--|---------------------------|------------------|
| 代码 | `qiniu_cert/`、`scripts/`、根 `docker-compose.yml` | `web/` + 复用 `qiniu_cert` |
| 配置 | `config.yaml` + `.env` | MySQL + `web/.env` |
| 证书 | `.local/acme/`（共享） | `.local/web/{user_id}/{cert_id}/acme/` |
| 定时 | `scheduler` / 宿主机 cron | 本容器 supercronic |
| 并行 | — | **不可**对同一域名双跑 |

Web **只读复用** `qiniu_cert` 与 `scripts/*_wrapper.sh` 做 deploy hook，**运行时不再读取**根目录 `config.yaml`。

## 快速开始（Docker）

```bash
cd web
cp .env.example .env   # 填写 SECRET_KEY / WEB_MASTER_KEY
docker compose -f docker-compose.web.yml up -d --build
```

浏览器打开 http://127.0.0.1:8000

## 从 v2 CLI 迁移

1. **导入配置**（凭证、配置档、证书记录）：

```bash
cd web
PYTHONPATH=..:. \
  PROJECT_ROOT="$(pwd)/.." WEB_DATA_ROOT="$(pwd)/../.local/web" \
  ../.venv/bin/python scripts/import_cli_config.py --email 你的登录邮箱
```

2. **迁入已签发证书**（免重新签发）：

```bash
../.venv/bin/python scripts/import_cli_certs.py --email 你的登录邮箱 --include-disabled
```

3. **停掉 v2**：`docker compose stop scheduler`（项目根目录），并删除宿主机 acme crontab。

4. Docker 卷同步与权限见 [docs/MIGRATION-v3.md](../docs/MIGRATION-v3.md)。

## 本地开发

```bash
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
2. **凭证**：列表 → 添加 / 编辑  
3. **配置档**：列表 → 添加 / 编辑（DNS + 部署类型 + 凭证）  
4. **添加域名**：选配置档 → `_qcert-verify` TXT 归属验证  
5. 验证通过后签发 / 部署；cron 每日复检归属（CLI 迁入证书见 `cli_imported` 豁免）

## 浏览器与 CDN

控制台 UI 使用 Material Web（CDN `esm.run`）与 Google Fonts。内网请改 `web/app/templates/base.html` 中的 import map 与字体链接。

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/import_cli_config.py` | v2 `config.yaml` → Web DB |
| `scripts/import_cli_certs.py` | v2 `.local/acme` 已签证书 → Web 目录 + DB |
| `scripts/cron-renew.sh` | 手动触发续签扫描 |
