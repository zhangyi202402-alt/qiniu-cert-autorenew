# Runbook — 七牛 HTTPS 证书全自动续签

## 快速安装

```bash
cd /path/to/qiniu-cert-autorenew
cp config.example.yaml config.yaml
export QINIU_AK=... QINIU_SK=... Tencent_SecretId=... Tencent_SecretKey=...
bash scripts/install.sh
```

## Phase 1 — ACME staging

`setup-acme.sh` 默认从 Gitee 安装 acme.sh（国内网络更稳定）：

```bash
git clone https://gitee.com/neilpang/acme.sh.git ~/.acme.sh
~/.acme.sh/acme.sh --install -m your@email.com --home ~/.acme.sh
```

或直接一键（含签发 + deploy）：

```bash
bash scripts/setup-acme.sh
```

确认 `~/.acme.sh/{domain}_ecc/{domain}.conf` 含 `Le_DeployHook='qiniu_wrapper'`。

## Phase 2 — Deploy Wrapper

手动触发：

```bash
python3 -m qiniu_cert.cli deploy -c config.yaml -d example.com \
  --key ~/.acme.sh/example.com_ecc/example.com.key \
  --fullchain ~/.acme.sh/example.com_ecc/fullchain.cer
```

## Phase 3 — Cron + 探活

```bash
bash scripts/install-cron.sh
bash scripts/tls-probe-cron.sh
```

## Phase 4 — Kodo 迁 CDN

对象存储自定义域名需纳入全自动续签时，将域名迁到融合 CDN：

| 步骤 | 控制台 | API |
|------|--------|-----|
| 1 | 融合 CDN → 域名管理 → 添加域名 | `POST /domain/{domain}` |
| 2 | 回源 → 七牛云存储 / 选择 Bucket | `PUT /domain/{domain}/source` |
| 3 | DNS CNAME 改为 CDN CNAME | — |
| 4 | 开启 HTTPS / 绑定证书 | `PUT .../sslize` 或 `httpsconf` |
| 5 | 取消对象存储空间域名绑定（避免冲突） | — |

将 CDN 域名加入 `config.yaml` 的 `qiniu_cdn_domains`，与 Deploy Wrapper 共用自动换证。

回归测试：

- [ ] 公开静态资源 HTTP/HTTPS 可访问
- [ ] 私有/签名 URL 不被 CDN 错误缓存
- [ ] Referer / IP 黑白名单仍生效
- [ ] 回源 Host 正确
- [ ] 上传/下载 Content-Type 正确
- [ ] 流量/费用在预期范围

## Phase 5 — 生产 CA

P0/P1 测试通过后：

```bash
acme.sh --set-default-ca --server letsencrypt
# 按域名 force 重新签发并 deploy，例如：
acme.sh --issue --dns dns_ali -d example.com -d '*.example.com' --force
acme.sh --deploy -d example.com --deploy-hook qiniu_wrapper
```

## 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| 401 fusion | QBox 签名/AK 错误 | 检查 AK/SK、系统 UTC 时间 |
| 401 api | Qiniu 鉴权 body 不一致 | 使用本 wrapper，勿用 acme 内置 qiniu hook |
| 400322 | 证书有效期 < 30 天 | 正常 LE 新证 90 天；检查是否用了过期 PEM |
| 400611 DELETE | 旧证仍绑定域名 | 等换绑 7 天后再 cleanup |
| 本地续签成功 CDN 未换证 | 未 `--deploy` 保存 hook | `acme.sh --deploy -d ... --deploy-hook qiniu_wrapper` |
| cron 静默失败 | 输出重定向 /dev/null | 使用 `install-cron.sh` 模板 |
