# qiniu-cert-autorenew

Automated Let's Encrypt certificate renewal and deployment for Qiniu CDN (acme.sh + deploy wrapper).

七牛 CDN HTTPS 证书全自动续签：ACME（Let's Encrypt）+ acme.sh + 自研 Deploy Wrapper。

> **Disclaimer:** Community-maintained tool, not affiliated with or endorsed by Qiniu. "Qiniu" is a trademark of Qiniu Limited. Use of Qiniu APIs is subject to their terms of service.

## 架构

```
acme.sh --cron
  → DNS-01 续签
  → deploy-hook qiniu_wrapper
  → POST fusion.qiniuapi.com/sslcert
  → PUT api.qiniu.com/domain/{d}/sslize|httpsconf
  → TLS 探活 + state.json
  → 旧 certID 延迟清理
```

## 特性

- 官方双端点 + 双鉴权（fusion QBox / api Qiniu）
- 多 CDN 域名部署失败自动记录明细（成功域名保留新证，不回滚）
- SAN 覆盖校验、TLS 探活（15min 重试）
- 旧 certID 延迟清理（7 天）
- 钉钉 / 飞书 webhook 告警

## 快速开始（Docker）

```bash
cp .env.example .env
# 编辑 .env 填写 QINIU_AK/SK、DNS 凭据

cp config.docker.example.yaml config.docker.yaml
# 编辑 config.docker.yaml 填写域名与 acme 邮箱

docker compose --profile setup run --rm setup   # 首次签发 + 部署
docker compose up -d scheduler                  # 定时续签 + 探活
```

详见 [docs/DOCKER.md](docs/DOCKER.md)。

## 本地安装

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
export QINIU_AK=... QINIU_SK=...
bash scripts/setup-acme.sh
```

## 命令

```bash
# Deploy（acme hook 或手动）
python3 -m qiniu_cert.cli deploy -c config.yaml -d example.com \
  --key KEY.pem --fullchain FULLCHAIN.pem

# 健康检查与旧证清理
python3 -m qiniu_cert.cli tls-probe -c config.yaml cdn.example.com --check-force-https
python3 -m qiniu_cert.cli cleanup -c config.yaml
```

## acme.sh 集成

```bash
cp scripts/qiniu_wrapper.sh ~/.acme.sh/deploy/
acme.sh --deploy -d example.com --deploy-hook qiniu_wrapper
bash scripts/install-cron.sh
```

## Kodo 存储域名

对象存储「空间 → 域名管理」无 HTTPS 换证 API。全自动需迁到 **融合 CDN → 域名管理 → 添加域名**，回源 Bucket，见 [docs/RUNBOOK.md](docs/RUNBOOK.md) Phase 4。

## 测试

```bash
python3 -m pytest tests/ -v
```

## 文档

- [RUNBOOK](docs/RUNBOOK.md) — 分阶段部署与故障排查
- [Docker Compose](docs/DOCKER.md)

## 致谢

- [acme.sh](https://github.com/acmesh-official/acme.sh) by Neil Peng
- [Let's Encrypt](https://letsencrypt.org/)

## License

[MIT](LICENSE) — see [SECURITY.md](SECURITY.md) for vulnerability reporting.
