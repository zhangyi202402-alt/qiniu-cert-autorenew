# Changelog

## 3.0.0 — 2026-08-31

**Web 控制台主线；与 v2 CLI 工作流不兼容（Breaking）。**

- **Web 控制台**（`web/`）：注册 / 登录、加密凭据、配置档、证书 CRUD、DNS TXT 归属验证、签发 / 续签 / 部署
- Material Web UI；凭证与配置档拆分为独立列表 / 新建 / 编辑页
- **CLI → Web 迁移工具**：`import_cli_config.py`（配置入库）、`import_cli_certs.py`（已签发证书迁入，免重签）
- CLI 迁入证书 `state_json.cli_imported`：无 Web TXT 时保持 `verified` 且允许续签
- 证书列表：有效期、最近更新、完整错误信息
- 定时：Web 容器 supercronic（02:00 归属复检、03:00 续签）

### Breaking changes（相对 v2.0.0 CLI）

- **勿与 v2 对同一批域名双跑 cron**（scheduler / 宿主机 acme crontab vs Web supercronic）
- 配置源从单文件 `config.yaml` 变为 **MySQL**；运行时 Web **不读取**根目录 `config.yaml`（仅导入脚本可读）
- 证书数据从共享 `.local/acme/` 变为 **`.local/web/{user_id}/{cert_id}/`**
- 新证书需 Web **TXT 归属验证**（CLI 迁入除外）
- v2 CLI-only 最终版见 tag **`v2.0.0`**；迁移说明 [docs/MIGRATION-v3.md](docs/MIGRATION-v3.md)

## 2.0.0 — 2026-08-22

Aliyun CLB certificate deployment alongside Qiniu CDN.

- **Aliyun CLB deploy**: CAS `UploadUserCertificate` (full PEM chain) → SLB `UploadServerCertificate` via `AliCloudCertificateId` → listener / SNI extension binding
- Certificate `targets` model with legacy `qiniu_cdn_domains` compatibility
- Per-certificate `key_type` (`rsa-2048` for CLB, `ec-256` default for CDN)
- `enabled: false` skips issue, probe, and deploy for a certificate entry
- `deploy --skip-probe` and CLB VIP-based TLS probe (`probe_host`)
- RAM docs for `yundun-cert:UploadUserCertificate` + SLB permissions ([docs/CLB.md](docs/CLB.md))
- Optional Docker build HTTP proxy args (cleared at runtime)

## 1.0.0 — 2026-06-21

Initial open-source release by 北京卡拉丁汽车技术服务有限公司 ([Kalading](https://www.kalading.com)), author zhangyi.

- ACME (Let's Encrypt) certificate renewal via acme.sh DNS-01
- Deploy wrapper: upload PEM to Qiniu fusion CDN and bind HTTPS (sslize / httpsconf)
- TLS health probe on deploy and scheduled cron checks
- Multi-domain partial failure handling (no rollback on failed domains)
- Delayed cleanup of previous cert IDs (7-day default)
- DingTalk / Feishu webhook alerts on deploy or probe failure
- Docker Compose deployment with supercronic scheduler
- Bare-metal install scripts for non-Docker environments
