# Docker Compose

## 准备

```bash
cp .env.example .env          # 填写 QINIU_AK/SK、Ali_Key/Ali_Secret 等
cp config.docker.example.yaml config.docker.yaml
# 编辑 config.docker.yaml（域名、dns_provider、cdn 域名）
```

可选环境变量（写入 `.env`）：

```bash
QINIU_CERT_CONFIG_FILE=./config.yaml   # 默认 ./config.docker.yaml
```

## 首次签发 + 部署七牛

```bash
docker compose --profile setup run --rm setup
```

数据写入 volume `qiniu-cert-data`（acme 私钥、state.json、日志）。

## 启动定时续签

```bash
docker compose up -d scheduler
```

默认 cron（容器 `TZ=Asia/Shanghai`）：

| 时间 | 任务 |
|------|------|
| 每天 00:08 | `acme.sh --cron`（续签 + deploy-hook） |
| 每天 08:15 | TLS 探活 + 旧证 cleanup |

> 定时器使用 supercronic，compose 中须写绝对路径 `/usr/local/bin/supercronic`（作为 PID 1 时会按 `argv[0]` 自重启，不能仅用 `supercronic`）。

日志：`docker compose exec scheduler tail -f /data/log/acme-qiniu.log`

## 手动命令

```bash
# 立即跑一轮续签
docker compose --profile tools run --rm renew

# 仅探活 + cleanup
docker compose --profile tools run --rm probe
```

## 数据持久化

| 容器路径 | 内容 |
|----------|------|
| `/data/acme` | acme.sh、私钥、`Le_DeployHook` |
| `/data/state/state.json` | certID 状态 |
| `/data/log/` | 运行日志 |

查看 volume：`docker volume inspect qiniu-cert-autorenew_qiniu-cert-data`

## 构建

```bash
docker compose build
```
