# 阿里云 CDN HTTPS 证书自动更换

将 Let's Encrypt 证书通过 `SetCdnDomainSSLCertificate` 部署到 [阿里云 CDN](https://cdn.console.aliyun.com/) 加速域名。

## 前置条件

- 加速域名已在 CDN 控制台添加，且 **HTTPS 加速类型** 已开启（或允许配置证书）
- DNS 解析走阿里云 DNS（`dns_ali`）或其它 acme.sh 支持的 DNS 插件
- RAM 子账号 AK/SK，建议最小权限：
  - `cdn:SetCdnDomainSSLCertificate`（必需）
  - `cdn:DescribeDomainCertificateInfo`（建议，便于排错）
  - `cdn:DescribeCdnDomainDetail`（建议）

## config.yaml 示例

```yaml
aliyun:
  access_key: "${ALIYUN_AK}"
  secret_key: "${ALIYUN_SK}"

certificates:
  - name: my-aliyun-cdn
    issue_domains:
      - cdn.example.com
      - static.example.com
    dns_provider: dns_ali
    dns_env:
      ali_key: Ali_Key
      ali_secret: Ali_Secret
    targets:
      - type: aliyun_cdn
        domains:
          - cdn.example.com
          - static.example.com
        https:
          force_https: true
```

与七牛 CDN 不同：**无需单独上传 certID 再绑定**，每个加速域名调用一次 OpenAPI 即可完成上传与启用。

## 算法

- 支持 **EC-256**（默认）与 RSA，**不像 CLB 强制 rsa-2048**
- 单条证书记录内所有 `aliyun_cdn.domains` 使用同一套 PEM

## acme deploy-hook

纯 `aliyun_cdn` target 时，`acme_plan` 自动选择 `cdn_wrapper`（见 `scripts/cdn_wrapper.sh`）。

```bash
docker compose --profile setup run --rm setup   # 首次签发
docker compose up -d scheduler                  # 定时续签
```

## 探活与失败策略

- 每个域名部署后 TLS 探活（可选 force HTTPS 检查）
- 多域名时：**单域名失败不回滚**已成功域名，错误信息聚合（与七牛 CDN 一致）

## 旧证清理

CDN `CertType=upload` 模式 **无独立证书删除 API**；工具仅在本地 `state.json` 记录 `aliyun_cdn:{domain}`，到期后清理 state，**不删除云端历史证书**。

## 常见问题

| 现象 | 可能原因 |
|------|----------|
| `InvalidDomain.Offline` | 域名未启用或已停用 |
| `certificate SAN does not cover` | 签发域名未覆盖加速域名 |
| 部署成功但探活失败 | CDN 回源/缓存未刷新，或 force HTTPS 未生效 |
| 与七牛 CDN 混淆 | 确认 `targets[].type` 为 `aliyun_cdn`，凭证为阿里云 AK/SK |
| `invalid key` / 七牛 Auth 报错 | 旧版会在构造 `DeployService` 时强制初始化七牛客户端；当前已懒加载，纯 `aliyun_cdn` 无需七牛 AK/SK |
| 浏览器显示 `(STAGING) …` 颁发者 | 使用了 `letsencrypt_test`；Web 将 `ACME_CA=letsencrypt` 后 recreate 容器并重签 |

## Web 控制台（v3）

1. 配置档 `deploy_type` 选 **阿里云 CDN**，部署凭证用阿里云 AK/SK  
2. 添加证书 → 配置 `_qcert-verify` TXT → 验证通过后 **签发**（首次不要点续签）  
3. 签发成功后再用列表 **部署 / 续签**

默认 `ACME_CA=letsencrypt_test`；生产切 `letsencrypt` 见 [web/README.md](../web/README.md)。
