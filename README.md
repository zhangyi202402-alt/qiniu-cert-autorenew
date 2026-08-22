# qiniu-cert-autorenew

Automated Let's Encrypt certificate renewal and deployment for **Qiniu CDN** and **Aliyun CLB** (acme.sh + deploy wrapper).

七牛 CDN / 阿里云 CLB HTTPS 证书全自动续签：ACME（Let's Encrypt）+ acme.sh + 自研 Deploy Wrapper。

**Maintained by [卡拉丁 Kalading](https://www.kalading.com)**（北京卡拉丁汽车技术服务有限公司）· Author: **zhangyi**

> **Disclaimer:** Open-source tool maintained by 北京卡拉丁汽车技术服务有限公司, not affiliated with or endorsed by Qiniu or Alibaba Cloud. "Qiniu" and "Alibaba Cloud" are trademarks of their respective owners. Use of their APIs is subject to their terms of service.

## 架构

```
acme.sh --cron（.local/acme）
  → DNS-01 续签
  → deploy-hook qiniu_wrapper / clb_wrapper
  → DeployRouter
       ├─ 七牛 CDN：upload sslcert → 绑定域名
       └─ 阿里云 CLB：CAS UploadUserCertificate → SLB 引用 → 换 HTTPS 监听（+SNI 扩展域）
  → TLS 探活 + .local/state/state.json
  → 旧证延迟清理
```

CLB 说明见 [docs/CLB.md](docs/CLB.md)。

## 目录结构

```
qiniu-cert-autorenew/
├── config.example.yaml
├── qiniu_cert/
│   ├── acme_plan.py
│   ├── cli.py
│   ├── config.py              # targets + 旧字段兼容
│   ├── deploy.py              # DeployRouter
│   ├── clients/
│   │   ├── aliyun_cas.py      # 证书服务（CAS）上传
│   │   └── aliyun_slb.py      # CLB OpenAPI
│   └── providers/
│       ├── qiniu_cdn.py
│       └── aliyun_clb.py
├── scripts/
│   ├── qiniu_wrapper.sh
│   ├── clb_wrapper.sh
│   └── ...
├── docs/CLB.md
├── Dockerfile
└── docker-compose.yml
```

## 数据目录

Docker 与裸机共用 **一份 `config.yaml`**，运行时数据均在项目 `.local/`（已 gitignore）：

| 路径 | 内容 |
|------|------|
| `.local/acme/` | acme.sh、私钥、域名 conf（`Le_DeployHook`） |
| `.local/state/state.json` | certID 状态 |
| `.local/log/acme-qiniu.log` | 运行日志 |

## 特性

- 官方双端点 + 双鉴权（fusion QBox / api Qiniu）
- **阿里云 CLB**：经 CAS 上传完整 PEM 链（含 LE 交叉签），再引用到 SLB 换绑
- 多目标部署失败自动记录明细（成功目标保留新证，不回滚）
- 证书 `enabled: false` 可跳过签发/探活/部署（便于维护窗口）
- SAN 覆盖校验、TLS 探活（可 `--skip-probe` 或直连 CLB VIP）
- 旧 certID 延迟清理（7 天）
- 钉钉 / 飞书 webhook 告警

## 快速开始（Docker）

```bash
cp .env.example .env
cp config.example.yaml config.yaml
# 编辑 .env 与 config.yaml
# 若使用阿里云 CLB：填写 ALIYUN_AK/SK，并配置 targets type: aliyun_clb（见 docs/CLB.md）

docker compose --profile setup run --rm setup   # 首次签发 + 部署
docker compose up -d scheduler                  # 定时续签 + 探活
```

Compose 将 `./config.yaml` 与 `./.local` 挂入容器，与裸机共用同一套数据。CLB 与七牛共用同一 scheduler。

**定时任务**（`TZ=Asia/Shanghai`）：每天 00:08 acme 续签；08:15 TLS 探活 + cleanup。

日志：`tail -f .local/log/acme-qiniu.log`（或 `docker compose exec scheduler tail -f /app/.local/log/acme-qiniu.log`）

```bash
docker compose --profile tools run --rm renew   # 立即续签一轮
docker compose --profile tools run --rm probe     # 仅探活 + cleanup
```

构建时若需 HTTP 代理，可传 `HTTP_PROXY` / `HTTPS_PROXY` build-arg（镜像内运行时已清空代理）。

## 裸机：acme.sh 集成（核心）

在 **git clone 目录**执行，与 Docker 使用相同的 `config.yaml` 和 `.local/`。

```bash
git clone https://github.com/zhangyi202402-alt/qiniu-cert-autorenew.git
cd qiniu-cert-autorenew
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml
cp .env.example .env
bash scripts/setup.sh         # 安装 acme 到 .local/acme，首次签发 + deploy
bash scripts/install-cron.sh
```

`setup.sh` 会处理 **config 中全部 `certificates`**，逐张签发并 deploy。默认从 GitHub 安装 acme.sh；国内网络慢时可设 `ACME_GIT_REPO=https://gitee.com/neilpang/acme.sh.git`。建议先用 `acme.ca: letsencrypt_test`，验证后再切生产。

**续签时机**：`acme.renew_days`（默认 30）表示证书**到期前 N 天**开始续签；设为 `15` 即剩余约 15 天时申请新证。Let's Encrypt 启用 ARI 时 CA 可能略早建议续签；若需严格按 `renew_days`，设 `acme.no_ari: true`。

确认 `.local/acme/{domain}_ecc/{domain}.conf` 含 `Le_DeployHook='qiniu_wrapper'`（CLB 证书为 `clb_wrapper`）。

## DNS 服务商（ACME DNS-01）

本项目 **不直接调用 DNS API**，签发时由 [acme.sh](https://github.com/acmesh-official/acme.sh) 的 DNS 插件添加 `_acme-challenge` TXT 记录。在 `config.yaml` 中为每张证书指定 `dns_provider` 与 `dns_env`，在 `.env` 中填写对应凭据即可。

| dns_provider | 适用场景 | `.env` 环境变量 | 权限说明 |
|--------------|----------|-----------------|----------|
| `dns_ali` | 阿里云云解析 DNS | `Ali_Key` / `Ali_Secret` | RAM：`AliyunDNSFullAccess` |
| `dns_tencent` | 腾讯云「云解析 DNS」 | `TENCENT_SECRET_ID` / `TENCENT_SECRET_KEY` | CAM：DNS 解析读写（如 `QcloudDNSPodFullAccess`） |
| `dns_dp` | **DNSPod**（独立 DNSPod 账号） | `DP_Id` / `DP_Key` | DNSPod 控制台 API 密钥 |
| `dns_cf` | Cloudflare | `CF_Token` 或 `CF_Email` + `CF_Key` | Zone DNS 编辑权限 |

> **腾讯云 vs DNSPod：** 域名在 [腾讯云 DNS 控制台](https://console.cloud.tencent.com/cns) 管理用 `dns_tencent`（CAM 密钥）；在 [DNSPod 独立控制台](https://www.dnspod.cn/) 管理用 `dns_dp`（DP_Id/DP_Key）。二者密钥体系不同，勿混用。

**腾讯云 DNS 配置示例：**

`config.yaml`：

```yaml
certificates:
  - name: my-site
    issue_domains:
      - example.com
    dns_provider: dns_tencent
    dns_env:
      tencent_id: TENCENT_SECRET_ID
      tencent_key: TENCENT_SECRET_KEY
    qiniu_cdn_domains:
      - cdn.example.com
```

`.env`：

```bash
TENCENT_SECRET_ID=AKIDxxxx
TENCENT_SECRET_KEY=xxxx
```

多张证书可使用 **不同 DNS 服务商**（例如 A 域名走阿里云、B 域名走腾讯云）；`dns_env` 中声明的变量会在签发前自动 `export` 给 acme.sh。完整示例见 `config.example.yaml` 与 `.env.example`。

修改 DNS provider 后需重新签发：`bash scripts/setup.sh` 或 `bash scripts/acme-issue-all.sh`。

## 手动 CLI（调试 / 排错）

```bash
python3 -m qiniu_cert.cli deploy -c config.yaml -d example.com \
  --key .local/acme/example.com_ecc/example.com.key \
  --fullchain .local/acme/example.com_ecc/fullchain.cer

# CLB 部署可跳过探活（例如公网仍指向旧证时）
python3 -m qiniu_cert.cli deploy -c config.yaml -d www.example.com \
  --key .local/acme/www.example.com/www.example.com.key \
  --fullchain .local/acme/www.example.com/fullchain.cer --skip-probe

python3 -m qiniu_cert.cli tls-probe -c config.yaml cdn.example.com --respect-config
python3 -m qiniu_cert.cli tls-probe-all -c config.yaml   # cron 同款：全部目标域名
python3 -m qiniu_cert.cli cleanup -c config.yaml
```

## Kodo 存储域名迁 CDN

| 步骤 | 控制台 | API |
|------|--------|-----|
| 1 | 融合 CDN → 域名管理 → 添加域名 | `POST /domain/{domain}` |
| 2 | 回源 → 七牛云存储 / 选择 Bucket | `PUT /domain/{domain}/source` |
| 3 | DNS CNAME 改为 CDN CNAME | — |
| 4 | 开启 HTTPS / 绑定证书 | `PUT .../sslize` 或 `httpsconf` |
| 5 | 取消对象存储空间域名绑定 | — |

将 CDN 域名加入 `config.yaml` 的 `qiniu_cdn_domains`。

## 切换生产 CA

```bash
export PATH="$(pwd)/.local/acme:$PATH"
export HOME="$(pwd)/.local/acme"
acme.sh --set-default-ca --server letsencrypt
acme.sh --issue --dns dns_ali -d example.com --force
acme.sh --deploy -d example.com --deploy-hook qiniu_wrapper
```

同时将 `config.yaml` 中 `acme.ca` 改为 `letsencrypt`。

## 从旧版迁移

若曾使用 `~/.acme.sh` 或 Docker volume `/data`：将 acme 数据迁到 `.local/acme`，state 迁到 `.local/state/`，或重新执行 `bash scripts/setup.sh` / `docker compose --profile setup run --rm setup`。

## 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| 401 fusion | QBox 签名/AK 错误 | 检查 AK/SK、系统 UTC 时间 |
| 401 api | Qiniu 鉴权 body 不一致 | 使用本 wrapper，勿用 acme 内置 qiniu hook |
| 400322 | 证书有效期 < 30 天 | 正常 LE 新证 90 天；检查是否用了过期 PEM |
| 400611 DELETE | 旧证仍绑定域名 | 等换绑 7 天后再 cleanup |
| 续签成功 CDN 未换证 | 未 `--deploy` 保存 hook | `acme.sh --deploy -d ... --deploy-hook qiniu_wrapper` |
| CLB CAS NoPermission | RAM 缺证书服务权限 | 增加 `yundun-cert:UploadUserCertificate`（见 docs/CLB.md） |
| CLB 探活失败 | 公网域名未指向该 CLB | 使用 `probe_host` + VIP 直连，或 `deploy --skip-probe` |
| cron 静默失败 | 输出重定向到 `.local/log/` | 查看 `acme-qiniu.log`；未装 acme 时先 `bash scripts/setup.sh` |
| DNS TXT 添加失败 | DNS 凭据错误或权限不足 | 核对 `dns_provider` / `dns_env` / `.env`；腾讯云勿与 DNSPod 密钥混用 |

## 测试

```bash
python3 -m pytest tests/ -v
```

## 致谢

- [acme.sh](https://github.com/acmesh-official/acme.sh) by Neil Peng
- [Let's Encrypt](https://letsencrypt.org/)

## License

[MIT](LICENSE) — Copyright © 2026 北京卡拉丁汽车技术服务有限公司. See [SECURITY.md](SECURITY.md) for vulnerability reporting.
