# SSL 证书 Web 服务 — 安全说明

## 凭据存储

- 用户密码使用 **bcrypt**（cost=12）哈希。
- 七牛 AK/SK、DNS API 密钥使用 **AES-256-GCM** 加密后写入 MySQL（`WEB_MASTER_KEY`）。
- 页面与 API **永不回显** Secret；日志禁止打印明文密钥。

## 域名归属

- 添加域名后须手动配置 `_qcert-verify.{domain}` TXT。
- 未验证禁止签发；归属丢失（`verification_status=lost`）后 **停止续签**，不删除已部署证书。

## 会话与 CSRF

- Session Cookie：`HttpOnly`、`SameSite=Lax`；生产环境建议反向代理 HTTPS 并启用 `Secure`。
- 所有状态变更表单使用 **CSRF token**（Session 绑定）。
- 登录失败限速：同 IP **5 次 / 分钟**。
- `SECRET_KEY` 须随机且保密。

## 配额与滥用

- 每用户默认最多 `max_certificates=10`，降低 Let's Encrypt 配额被滥用风险。
- ACME 默认使用 `ACME_CA=letsencrypt_test`；生产切换 `letsencrypt` 前完成 E2E。

## 部署建议

- 单 worker（`uvicorn --workers 1`），配合 BackgroundTasks。
- `issuing`/`renewing` 超过 15 分钟自动回收为 `failed`。
- 非 root 容器用户运行；`.local/web/{user_id}/{cert_id}/` 目录隔离。

## 免责声明

本 Web 控制台基于开源工具 qiniu-cert-autorenew，非七牛 / 阿里云 / 腾讯云官方产品。使用各云 API 须遵守其服务条款。
