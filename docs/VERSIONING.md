# 版本说明

本项目有两条产品线，**大版本号区分 CLI 与 Web**，同一主版本内不再混用两套运行方式。

## 版本线

| 版本 | 代号 | 形态 | Git 基准 | 状态 |
|------|------|------|----------|------|
| **1.x** | — | 七牛 CDN CLI | 历史 tag `v1.0.0` | 已停止维护 |
| **2.x** | CLI | `config.yaml` + `.local/acme` + scheduler | commit `2585cf7` / tag **`v2.0.0`** | **CLI 最终线**（无 Web UI） |
| **3.x** | Web | `web/` + MySQL + `.local/web` | `feat/web-material-credentials` 及之后 | **当前主线** |

- **v2.0.0**：最后一条「仅 CLI / Docker scheduler、无 Web 控制台」的正式版本。
- **v3.0.0 起**：Web 控制台为推荐运行方式；与 v2 **配置、数据目录、定时任务均不兼容**（见 [MIGRATION-v3.md](MIGRATION-v3.md)）。

## 不兼容摘要（v2 CLI ↔ v3 Web）

| 项目 | v2 CLI | v3 Web |
|------|--------|--------|
| 配置 | 根目录 `config.yaml` + `.env` | MySQL + `web/.env`（`WEB_MASTER_KEY` 加密凭据） |
| 证书 / acme | 共享 `.local/acme/` | 每用户每证书 `.local/web/{user_id}/{cert_id}/acme/` |
| 定时续签 | `scheduler` 容器或宿主机 `cron-acme.sh` | `web` 容器内 supercronic |
| 域名归属 | 无（签发即 DNS-01） | Web TXT `_qcert-verify`（CLI 迁入可标记 `cli_imported`） |
| 多用户 | 不支持 | 支持 |
| 同时跑两套 cron | v2 文档曾写「可并行」 | **v3 起禁止对同一批证书双跑**，会重复续签/部署 |

## 如何选择

- **继续纯 CLI、不要 Web**：检出 **`v2.0.0`**（或 `main` 在 Web 合并前的 commit），不要用 v3 的 `web/docker-compose.web.yml` 接管同一域名。
- **迁到 Web**：按 [MIGRATION-v3.md](MIGRATION-v3.md) 导入配置与证书，**停掉** v2 的 scheduler 与宿主机 acme crontab，只保留 Web 定时任务。

## 查看版本

```bash
python -c "import qiniu_cert; print(qiniu_cert.__version__)"
# 3.0.0
```

Web 容器内 `PROJECT_ROOT` 与 CLI 共用同一 `qiniu_cert` 包版本号。

## 打 tag（维护者）

```bash
# CLI 最终版（若尚未打 tag）
git tag -a v2.0.0 2585cf7 -m "CLI-only final release (no Web UI)"

# Web 正式版（在 v3 功能合并并验证后）
git tag -a v3.0.0 -m "Web console; breaking change from v2 CLI workflow"
```
