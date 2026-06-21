# Changelog

## 1.0.0 — 2026-06-21

Initial open-source release.

- ACME (Let's Encrypt) certificate renewal via acme.sh DNS-01
- Deploy wrapper: upload PEM to Qiniu fusion CDN and bind HTTPS (sslize / httpsconf)
- TLS health probe on deploy and scheduled cron checks
- Multi-domain partial failure handling (no rollback on failed domains)
- Delayed cleanup of previous cert IDs (7-day default)
- DingTalk / Feishu webhook alerts on deploy or probe failure
- Docker Compose deployment with supercronic scheduler
- Bare-metal install scripts for non-Docker environments
