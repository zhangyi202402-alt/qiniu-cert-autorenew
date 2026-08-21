# 阿里云 CLB 证书自动续签

同仓库扩展：在现有七牛 CDN 链路旁，支持传统型负载均衡（CLB）HTTPS 证书上传与换绑。

## 配置

```yaml
aliyun:
  access_key: "${ALIYUN_AK}"
  secret_key: "${ALIYUN_SK}"

certificates:
  - name: example-clb
    issue_domains:
      - www.example.com
    key_type: rsa-2048          # CLB 强制 RSA，禁止 ec-256
    dns_provider: dns_ali
    dns_env:
      ali_key: Ali_Key
      ali_secret: Ali_Secret
    targets:
      - type: aliyun_clb
        region_id: cn-hangzhou
        load_balancer_id: lb-xxxxxxxx
        listener_port: 443
        domain_extensions: []   # SNI 扩展域名；有则必须全部换绑
        # probe_host: www.example.com
```

`.env`：

```bash
ALIYUN_AK=...
ALIYUN_SK=...
# 或 ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET
```

旧配置仅写 `qiniu_cdn_domains` 仍可用（自动合成 `qiniu_cdn` target）。

## RAM 最小权限

```
slb:UploadServerCertificate
slb:DeleteServerCertificate
slb:SetLoadBalancerHTTPSListenerAttribute
slb:DescribeLoadBalancerHTTPSListenerAttribute
slb:DescribeDomainExtensions
slb:SetDomainExtensionAttribute
```

## 流程

1. `acme.sh` 按证书 `key_type` 签发（CLB 用 `rsa-2048`）
2. deploy-hook `clb_wrapper`（或混部时 `qiniu_wrapper`）调用 `cli deploy`
3. `UploadServerCertificate` → `SetLoadBalancerHTTPSListenerAttribute`
4. 若有 `domain_extensions`：Describe → `SetDomainExtensionAttribute`
5. 按域名 TLS 探活（SNI）→ 写 `state.json`（key 形如 `clb:{region}:{lb_id}:{port}`）
6. `old_cert_cleanup_days` 后删除旧 `ServerCertificateId`（仍被其它 state 引用则跳过）

## 风险

| 风险 | 说明 |
|------|------|
| SNI 漏换 | 只改默认证会导致扩展域仍挂旧证；配置了 extensions 会强制循环换绑并分域探活 |
| 换证闪断 | 官方提示可能数秒 SSL 中断，建议低峰 |
| ECC | CLB 不支持；配置阶段与上传前双重校验 |

## 验收（staging）

```bash
# 1. 配置 aliyun_clb + key_type: rsa-2048，acme.ca 可用 letsencrypt_test
bash scripts/setup.sh   # 或仅对 CLB 证书 issue+deploy

# 2. 探活
.venv/bin/python -m qiniu_cert.cli -c config.yaml tls-probe-all

# 3. openssl 确认（带 SNI）
openssl s_client -connect www.example.com:443 -servername www.example.com </dev/null 2>/dev/null | openssl x509 -noout -issuer -dates
```

## Phase 2（未实现）

- Certum ACME + EAB
- ALB / NLB
- 包名 rename（`qiniu_cert` → 更中性名称）
