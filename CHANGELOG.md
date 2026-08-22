# Changelog

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
