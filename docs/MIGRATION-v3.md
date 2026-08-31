# 从 v2 CLI 迁移到 v3 Web

v3 与 v2 **不共享** acme 目录与 cron。迁移后应只保留 Web 一套自动续签。

## 1. 准备 Web

```bash
cd web
cp .env.example .env   # SECRET_KEY、WEB_MASTER_KEY
docker compose -f docker-compose.web.yml up -d --build
```

浏览器注册账号（例如 `ops@example.com`）。

## 2. 导入 CLI 配置（凭证 / 配置档 / 证书记录）

将根目录 `config.yaml` + `.env` 写入 MySQL（幂等）：

```bash
cd web
PYTHONPATH=..:. \
  DATABASE_URL='mysql+pymysql://qcert:secret@127.0.0.1:3307/qiniu_cert_web?charset=utf8mb4' \
  PROJECT_ROOT=.. WEB_DATA_ROOT=../.local/web \
  ../.venv/bin/python scripts/import_cli_config.py --email 你的登录邮箱
```

## 3. 迁入已签发的 CLI 证书（免重新签发）

```bash
../.venv/bin/python scripts/import_cli_certs.py \
  --email 你的登录邮箱 \
  --include-disabled
```

- 从 `.local/acme/` 复制证书与 acme.sh 环境到 `.local/web/{user_id}/{cert_id}/acme/`
- 数据库标记 `active` / `verified`，并设置 `state_json.cli_imported=true`（无 Web TXT 时不阻断续签）
- Docker 部署需保证卷内文件属主为容器 `app` 用户（见下文）

## 4. 停掉 v2 定时任务（必做）

```bash
# 根目录 CLI scheduler
docker compose stop scheduler

# 宿主机 crontab 中删除 acme.sh --cron 行（若有）
crontab -l   # 确认无 qiniu-cert-autorenew/.local/acme
```

**不要**再执行 `docker compose up -d scheduler`，否则与 Web 重复续签。

## 5. Docker 卷与路径

- Web 容器使用命名卷 `web_data` → `/app/.local/web`
- 若在宿主机执行 `import_cli_certs.py` 后再用 Docker，需同步数据并修正属主：

```bash
docker cp .local/web/. web-web-1:/app/.local/web/
docker compose -f web/docker-compose.web.yml exec -T -u root web chown -R app:app /app/.local/web
```

- 数据库 `acme_home` 在容器内应为 `/app/.local/web/...`（勿留宿主机绝对路径）

## 6. 验证

```bash
docker compose -f web/docker-compose.web.yml exec -T web python -m app.jobs.verify_all
docker compose -f web/docker-compose.web.yml exec -T web python -m app.jobs.renew_all
```

列表页应显示「正常 / 已验证 / 有效期」；续签日志可为 `acme cron ok (no renewal needed)`（距到期尚早时正常）。

## 7. 可选：补 Web TXT 归属

CLI 迁入证书不强制 TXT。若希望走标准 Web 归属流程，可在 DNS 添加验证页所示 `_qcert-verify` TXT；验证成功后不再依赖 `cli_imported` 豁免。

## 回滚到 v2 CLI

仅当 **尚未** 在 Web 上续签/部署过、且仍保留 `.local/acme` 原数据时：

1. 停 Web：`docker compose -f web/docker-compose.web.yml down`
2. 检出 `v2.0.0` 或使用未合并 Web 的 commit
3. `docker compose up -d scheduler`

不要在 v2 与 v3 之间来回切换同一域名的 cron。
