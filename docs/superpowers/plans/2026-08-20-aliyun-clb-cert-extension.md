# 同 Repo 扩展阿里云 CLB 证书自动续签 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `qiniu-cert-autorenew` 仓库内，以最小破坏性扩展支持阿里云传统型负载均衡（CLB）HTTPS 证书的自动签发、上传、换绑、探活与旧证清理，且不破坏现有七牛 CDN 链路。

**Architecture:** 同一 `certificates[]` 配置通过 `targets[]`（或兼容旧字段）声明部署目标；CLI `deploy` 按证书记录路由到 Qiniu CDN 或 Aliyun CLB provider。签发仍由 acme.sh 完成；CLB 强制 RSA-2048；换绑走 `UploadServerCertificate` + `SetLoadBalancerHTTPSListenerAttribute`（扩展域另调 `SetDomainExtensionAttribute`）。首版 CA 默认沿用 Let's Encrypt；Certum（EAB）列为 Phase 2，不阻塞首版交付。

**Tech Stack:** Python 3.12、PyYAML、cryptography、requests、现有 acme.sh / Docker Compose / supercronic；阿里云 OpenAPI（SLB `2014-05-15`，HMAC-SHA1 签名或官方 SDK，本计划优先 **纯 requests + 签名** 以减少依赖，与现有 `qiniu_client` 风格一致）。

## Global Constraints

- 同 repo 扩展：不新建独立仓库；包名暂保持 `qiniu_cert`（Phase 后可选 rename，本 plan 不做）。
- 现有 `config.yaml` 仅含 `qiniu_cdn_domains` 时必须继续可加载、可 deploy（向后兼容）。
- 一张 `certificates` 记录默认 **一个** 主要 target 类型；禁止同一记录同时要求 `ec-256` 与 CLB（算法冲突）。
- CLB 证书算法：**仅 RSA-2048**（上传前硬校验；拒绝 ECC）。
- CLB 私钥上传格式：PKCS#1 `BEGIN RSA PRIVATE KEY`；若为 PKCS#8 则在 deploy 内转换。
- 多 target / 多绑定对象失败策略：与七牛一致——**单对象失败不回滚已成功对象**，写 state 仅成功项，告警聚合失败。
- 扩展域名（SNI）：若配置了 `domain_extensions`，必须全部尝试换绑；探活必须按域名带 SNI。
- 旧证删除：延迟 `old_cert_cleanup_days`；删除前确认 state 中无其它域仍引用同一 `ServerCertificateId`（同 region）。
- 不实现：ALB/NLB、双向认证 CA、阿里云官方「证书托管」一键部署、Certum EAB（Phase 2）。
- 测试：新增单测用 mock HTTP，不打真网；现有 `tests/test_deploy.py` 等必须继续通过。
- 文档与注释：用户可见说明用中文；提交信息英文或中文均可，与仓库近期风格一致。
- 密钥：`.env` 增加阿里云 AK/SK；禁止提交真实凭据。

---

## 架构决策（ADR 摘要）

| 决策 | 选择 | 理由 |
|------|------|------|
| 扩展方式 | 同 repo + provider 路由 | 共用 acme/cron/Docker/告警；运维一套 |
| 配置模型 | `targets[]` + 旧字段兼容 | 避免一次改光现网 config |
| 客户端 | 自研 `aliyun_slb.py`（requests） | 对齐 `qiniu_client`；少依赖 |
| 状态 | 扩展 `DomainState` 或 state key 带前缀 | CLB 用 `clb:{region}:{lb_id}:{port}` 或域名键；扩展域单独键 |
| CA 首版 | Let's Encrypt + `rsa-2048` | 与现有工具链统一；Certum 后置 |
| 包目录 | `qiniu_cert/providers/` + `clients/` | 渐进拆分，避免一次性大搬家 |

```
acme.sh --cron / --deploy-hook
  → scripts/deploy_wrapper.sh（或 qiniu_wrapper / clb_wrapper）
  → python -m qiniu_cert.cli deploy -d <issue_domain>
  → DeployRouter
       ├─ QiniuCdnProvider（现逻辑）
       └─ AliyunClbProvider（新）
            UploadServerCertificate
            → SetLoadBalancerHTTPSListenerAttribute
            → [SetDomainExtensionAttribute...]
            → TLS probe (SNI)
            → StateStore
```

---

## 文件地图

| 路径 | 职责 |
|------|------|
| `qiniu_cert/config.py` | 解析 `targets`、可选 `key_type`、`aliyun` 凭据；兼容旧 `qiniu_cdn_domains` |
| `qiniu_cert/clients/aliyun_slb.py` | SLB OpenAPI：upload / set listener / describe / domain extension / delete cert |
| `qiniu_cert/providers/qiniu_cdn.py` | 从现 `deploy.py` 迁出的七牛逻辑 |
| `qiniu_cert/providers/aliyun_clb.py` | CLB 部署编排 |
| `qiniu_cert/deploy.py` | `DeployRouter`：按 config 调 provider |
| `qiniu_cert/cert_utils.py` | `assert_rsa_2048`、`to_pkcs1_pem`、既有 probe |
| `qiniu_cert/state.py` | 可选扩展字段；cleanup 按 provider 删证 |
| `qiniu_cert/cli.py` | deploy/cleanup/tls-probe-all 感知 CLB |
| `scripts/clb_wrapper.sh` | acme deploy-hook 入口（可复用同一 cli） |
| `config.example.yaml` / `.env.example` | 示例与环境变量 |
| `docs/CLB.md` | CLB 使用说明与风险 |
| `tests/test_config_targets.py` | 配置兼容 |
| `tests/test_aliyun_slb.py` | 签名与请求构造 |
| `tests/test_aliyun_clb_deploy.py` | 部署编排 mock |

---

## Execution status (2026-08-21)

Implemented on branch `feat/aliyun-clb-cert-extension`. Follow-up white-box fixes:

- P0: `acme_keylength()` maps `rsa-2048` → acme `--keylength 2048`
- P1: RSA min 2048-bit assert + cleanup shared-id unit test
- P2: SLB `_rpc` error handling cleaned; dead config branch removed
- P3: CLB/Docker DoD documented in `docs/CLB.md`

Task 8 staging against real CLB remains a manual gate.

---

### Task 1: 配置模型 — targets 与向后兼容

**Files:**
- Modify: `qiniu_cert/config.py`
- Modify: `config.example.yaml`
- Modify: `.env.example`
- Test: `tests/test_config_targets.py`

**Interfaces:**
- Produces:
  - `@dataclass TargetQiniuCdn: domains: list[str]; https: HttpsConfig`
  - `@dataclass TargetAliyunClb: region_id: str; load_balancer_id: str; listener_port: int; domain_extensions: list[str]; probe_host: str | None`
  - `@dataclass CertificateConfig: ...; key_type: str | None; targets: list[TargetQiniuCdn | TargetAliyunClb]`
  - `AppConfig.aliyun_ak: str; AppConfig.aliyun_sk: str`
  - `def iter_targets(cert: CertificateConfig) -> list[...]:` 若 `targets` 空且存在 `qiniu_cdn_domains`，合成一个 `TargetQiniuCdn`
  - `def effective_key_type(cert: CertificateConfig, acme: AcmeConfig) -> str`

- [x] **Step 1: Write the failing test**

```python
# tests/test_config_targets.py
from pathlib import Path
import textwrap
from qiniu_cert.config import load_config, iter_targets, effective_key_type

def test_legacy_qiniu_cdn_domains_still_loads(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent("""
        qiniu: {access_key: "ak", secret_key: "sk"}
        acme: {email: "a@b.com", ca: letsencrypt, key_type: ec-256}
        certificates:
          - name: legacy
            issue_domains: [cdn.example.com]
            dns_provider: dns_ali
            qiniu_cdn_domains: [cdn.example.com]
        paths: {state_file: state.json}
    """), encoding="utf-8")
    cfg = load_config(p)
    targets = list(iter_targets(cfg.certificates[0]))
    assert len(targets) == 1
    assert targets[0].type == "qiniu_cdn"
    assert targets[0].domains == ["cdn.example.com"]

def test_aliyun_clb_target_and_rsa_override(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent("""
        qiniu: {access_key: "", secret_key: ""}
        aliyun: {access_key: "aak", secret_key: "ask"}
        acme: {email: "a@b.com", ca: letsencrypt, key_type: ec-256}
        certificates:
          - name: clb1
            issue_domains: [www.example.com]
            key_type: rsa-2048
            dns_provider: dns_ali
            targets:
              - type: aliyun_clb
                region_id: cn-hangzhou
                load_balancer_id: lb-xxx
                listener_port: 443
                domain_extensions: [api.example.com]
        paths: {state_file: state.json}
    """), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.aliyun_ak == "aak"
    t = list(iter_targets(cfg.certificates[0]))[0]
    assert t.type == "aliyun_clb"
    assert t.load_balancer_id == "lb-xxx"
    assert effective_key_type(cfg.certificates[0], cfg.acme) == "rsa-2048"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd qiniu-cert-autorenew && .venv/bin/pytest tests/test_config_targets.py -v`  
Expected: FAIL（`iter_targets` / `aliyun` 未定义）

- [ ] **Step 3: Implement config parsing**

在 `CertificateConfig` 增加可选字段；`load_config` 解析 `aliyun` 与 `targets`；保留 `qiniu_cdn_domains: list[str] = field(default_factory=list)`。  
`TargetAliyunClb.type` 用字面量属性 `type: str = "aliyun_clb"`（dataclass 字段或 property）。  
校验：若 target 含 `aliyun_clb` 且 `effective_key_type` 不是 `rsa-2048` / `2048`，`load_config` **警告或 raise**（本 plan：**raise `ValueError`**，避免错误签发后再失败）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config_targets.py -v`  
Expected: PASS

- [ ] **Step 5: Update examples**

更新 `config.example.yaml` 增加注释掉的 CLB 示例；`.env.example` 增加：

```bash
# 阿里云 CLB（OpenAPI）
ALIYUN_AK=
ALIYUN_SK=
# 亦支持 ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET
```

`load_config` 读取顺序：`aliyun.access_key` → env `ALIYUN_AK` → `ALIBABA_CLOUD_ACCESS_KEY_ID`。

- [ ] **Step 6: Commit**

```bash
git add qiniu_cert/config.py config.example.yaml .env.example tests/test_config_targets.py
git commit -m "$(cat <<'EOF'
feat: add certificate targets config with CLB and legacy qiniu compat

EOF
)"
```

---

### Task 2: cert_utils — RSA 校验与 PKCS#1 转换

**Files:**
- Modify: `qiniu_cert/cert_utils.py`
- Test: `tests/test_cert_utils_rsa.py`

**Interfaces:**
- Produces:
  - `def ensure_rsa_private_key_pkcs1(pem: str) -> str`
  - `def assert_certificate_rsa(fullchain_pem: str) -> None`  # 叶证书公钥为 RSA，否则 DeployError
- Consumes: `DeployError`, cryptography

- [ ] **Step 1: Write failing tests**（用 cryptography 现场生成临时 RSA/EC PEM 夹具）

```python
def test_ensure_rsa_pkcs1_accepts_rsa():
    # generate rsa key pem → ensure returns BEGIN RSA PRIVATE KEY
    ...

def test_assert_certificate_rsa_rejects_ec():
    # ec leaf → raises DeployError
    ...
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/pytest tests/test_cert_utils_rsa.py -v`

- [ ] **Step 3: Implement helpers in `cert_utils.py`**

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add RSA-2048 and PKCS#1 helpers for CLB uploads"
```

---

### Task 3: Aliyun SLB API 客户端

**Files:**
- Create: `qiniu_cert/clients/__init__.py`
- Create: `qiniu_cert/clients/aliyun_slb.py`
- Test: `tests/test_aliyun_slb.py`

**Interfaces:**
- Produces class `AliyunSlbClient`:
  - `__init__(self, access_key_id: str, access_key_secret: str)`
  - `upload_server_certificate(self, *, region_id: str, server_certificate: str, private_key: str, server_certificate_name: str) -> str`  # returns ServerCertificateId
  - `set_https_listener_certificate(self, *, region_id: str, load_balancer_id: str, listener_port: int, server_certificate_id: str) -> None`
  - `describe_domain_extensions(self, *, region_id: str, load_balancer_id: str, listener_port: int) -> list[dict]`  # DomainExtensionId, Domain
  - `set_domain_extension_certificate(self, *, region_id: str, domain_extension_id: str, server_certificate_id: str) -> None`
  - `delete_server_certificate(self, *, region_id: str, server_certificate_id: str) -> None`
- Raises: `AliyunSlbError(message, code: str | None = None)`

签名：阿里云 RPC 风格（`Format=JSON`, `Version=2014-05-15`, `SignatureMethod=HMAC-SHA1`, `SignatureVersion=1.0`），`Endpoint=https://slb.aliyuncs.com`（或区域 endpoint，实现时以官方文档为准；单测 mock `requests.Session.request`）。

- [ ] **Step 1: Write failing test for signature canonicalization + upload parses ServerCertificateId**

```python
def test_upload_server_certificate_parses_id(monkeypatch):
    client = AliyunSlbClient("ak", "sk")
    def fake_request(method, url, **kwargs):
        class R:
            status_code = 200
            def json(self):
                return {"ServerCertificateId": "15015-cn-hangzhou"}
            text = "{}"
        return R()
    monkeypatch.setattr(client.session, "request", fake_request)
    cid = client.upload_server_certificate(
        region_id="cn-hangzhou",
        server_certificate="-----BEGIN CERTIFICATE-----\nA\n-----END CERTIFICATE-----",
        private_key="-----BEGIN RSA PRIVATE KEY-----\nB\n-----END RSA PRIVATE KEY-----",
        server_certificate_name="t1",
    )
    assert cid == "15015-cn-hangzhou"
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `aliyun_slb.py`**（含 `_sign` / `_rpc`）

- [ ] **Step 4: Run — PASS**；并补 `set_https_listener` / `describe_domain_extensions` 各一则 mock 测试

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add Aliyun SLB OpenAPI client for certificate ops"
```

---

### Task 4: 拆分 Qiniu provider + DeployRouter

**Files:**
- Create: `qiniu_cert/providers/__init__.py`
- Create: `qiniu_cert/providers/qiniu_cdn.py`（迁入现 `DeployService` 主体）
- Modify: `qiniu_cert/deploy.py` → `DeployRouter`
- Modify: `qiniu_cert/cli.py`（若需）
- Test: 现有 `tests/test_deploy.py` 必须改 import 后仍绿

**Interfaces:**
- Produces:
  - `class QiniuCdnProvider: def deploy(self, cert_cfg, issue_domain, key_pem, fullchain_pem) -> str`
  - `class DeployRouter: def deploy_from_files(self, issue_domain, key_path, fullchain_path) -> str`  
    行为：对 `iter_targets(cert_cfg)` 逐个调用；若仅 qiniu，返回 cert_id 字符串（保持 CLI 打印兼容）；若含 CLB，返回主结果摘要字符串（如 `qiniu:xxx;clb:yyy`）或最后一个成功 id——**约定：返回 JSON 一行摘要或 `ok`，CLI 打印 `deploy ok ...`**。  
    明确约定：**首版若记录含多个 targets，全部执行；返回值用分号拼接各 provider 结果 id。**

- [ ] **Step 1: Move code + fix imports；run existing tests**

Run: `.venv/bin/pytest tests/test_deploy.py tests/test_acme_plan.py -v`  
Expected: PASS（行为不变）

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: extract QiniuCdnProvider behind DeployRouter"
```

---

### Task 5: AliyunClbProvider 部署编排

**Files:**
- Create: `qiniu_cert/providers/aliyun_clb.py`
- Modify: `qiniu_cert/deploy.py`（router 注册 CLB）
- Modify: `qiniu_cert/state.py`（state key 约定）
- Test: `tests/test_aliyun_clb_deploy.py`

**Interfaces:**
- Produces:
  - `class AliyunClbProvider:`
    - `__init__(self, config: AppConfig)`
    - `def deploy(self, cert_cfg: CertificateConfig, target: TargetAliyunClb, issue_domain: str, key_pem: str, fullchain_pem: str) -> str`
- State key 约定：
  - 默认监听：`clb:{region_id}:{load_balancer_id}:{listener_port}`
  - 扩展域：`clb:{region_id}:{load_balancer_id}:{listener_port}:{domain}`
- `DomainState.current_cert_id` 存 `ServerCertificateId`
- 流程（必须按序）：
  1. `assert_certificate_rsa` + `ensure_rsa_private_key_pkcs1`
  2. SAN 覆盖 `probe_host` 或 `issue_domains[0]` 以及每个 `domain_extensions`
  3. `upload_server_certificate` → `new_id`
  4. `set_https_listener_certificate`
  5. `describe_domain_extensions`，对配置中每个 domain 匹配 `DomainExtensionId` 并 `set_domain_extension_certificate`；找不到则记 failure（不回滚监听）
  6. TLS probe：对 `probe_host or issue_domains[0]` 与每个 extension domain 调用现有 `tls_probe`（需确认 `tls_probe` 支持 SNI server_name——若当前仅按 host 连，则扩展 `tls_probe(host, min_valid_days, server_hostname=None)`）
  7. 成功项 `state.update_after_deploy`

- [ ] **Step 1: Write failing orchestration test with mocks**

```python
def test_clb_deploy_uploads_sets_listener_and_extension(monkeypatch, tmp_path):
    # mock AliyunSlbClient methods; assert call order;
    # domain_extensions=["api.example.com"] → set_domain_extension called
    ...
```

- [ ] **Step 2: Implement provider + router branch + tls_probe SNI 参数（若缺）**

- [ ] **Step 3: pytest PASS**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: deploy certificates to Aliyun CLB HTTPS listeners"
```

---

### Task 6: cleanup 与 CLI / hook

**Files:**
- Modify: `qiniu_cert/deploy.py` 或 providers 的 `cleanup_old_certs`
- Modify: `qiniu_cert/cli.py`
- Create: `scripts/clb_wrapper.sh`（可与 qiniu_wrapper 同调 `cli deploy`，因 router 已分流——**推荐：单一 `scripts/cert_wrapper.sh` 复制自 qiniu_wrapper，两边 hook 都指向它；或 clb_wrapper 内容与 qiniu_wrapper 相同**）
- Modify: `scripts/setup.sh` / `docker/setup.sh`（若存在）：按证书 `effective_key_type` 传 `--keylength`；CLB 记录安装 `clb_wrapper` 为 deploy-hook

**Interfaces:**
- `cleanup_old_certs`：若 state key 以 `clb:` 开头，调用 `AliyunSlbClient.delete_server_certificate`；否则走七牛删除。
- 删除前：扫描全部 state，若 `previous_cert_id` 仍等于其它域的 `current_cert_id`，跳过删除并打日志。

- [ ] **Step 1: Test cleanup skips shared cert id**

- [ ] **Step 2: Implement**

- [ ] **Step 3: Add `scripts/clb_wrapper.sh`（与 qiniu_wrapper 同等调用 cli）**

- [ ] **Step 4: setup 脚本：对 `aliyun_clb` 目标使用 `--keylength 2048` 与 `--deploy-hook clb_wrapper`**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: CLB cleanup, deploy hook, and setup keylength routing"
```

---

### Task 7: 文档与验收清单

**Files:**
- Create: `docs/CLB.md`
- Modify: `README.md`（架构图增加 CLB 分支；链到 `docs/CLB.md`）
- Modify: `docs/DOCKER.md`（若需：同一 compose，仅多 AK）

**内容必须覆盖：**
- 配置示例（LE + rsa-2048 + aliyun_clb）
- RAM 权限列表（见前序调研）
- 风险：换证闪断、SNI 漏换、禁止 ECC
- 验收步骤：staging LE → upload → 换监听 → openssl s_client -servername
- Phase 2 预告：Certum EAB（不实现）

- [ ] **Step 1: Write docs**

- [ ] **Step 2: Commit**

```bash
git commit -m "docs: document Aliyun CLB certificate automation"
```

---

### Task 8: 联调验收（人工 / staging）

**不写生产破坏性操作；在计划中作为完成定义（DoD）。**

- [ ] **Step 1:** 使用 **Let's Encrypt staging** + 测试 CLB（或专用监听）跑通：issue → deploy → probe
- [ ] **Step 2:** 确认扩展域（若有）证书一致
- [ ] **Step 3:** 确认七牛现网配置回归：`pytest` 全绿 + 一次 qiniu deploy dry 路径（mock 或 staging）
- [ ] **Step 4:** 记录 certID / ServerCertificateId 到 runbook 笔记（勿提交密钥）

---

## 风险与缓解（写入实现纪律）

| 风险 | 等级 | 缓解（本 plan 强制） |
|------|------|----------------------|
| SNI 只换默认证 | 高 | Task 5 强制 extension 循环 + 分域探活 |
| ECC 上传失败或误用 | 高 | Task 1 raise + Task 2 assert |
| 换证闪断 | 中高 | 文档要求低峰；probe 重试沿用 `probe_retries` |
| 旧证误删 | 中 | Task 6 引用检查 |
| 配置破坏七牛 | 中 | Task 1 兼容测试 + Task 4 回归 |

---

## Phase 2（本 plan 明确不做）

- Certum ACME Directory + EAB 配置项（`acme.ca: certum` + `eab_kid` / `eab_hmac`）
- ALB/NLB provider
- 包名 rename（`qiniu_cert` → `cert_autorenew`）
- 阿里云 SSL 托管自动部署替代自建换绑

---

## Self-Review

1. **Spec coverage:** 同 repo、targets 兼容、SLB API、RSA、SNI、不回滚、cleanup、hook/setup、文档、LE 优先 / Certum 后置 —— 均有对应 Task。  
2. **Placeholder scan:** 无 TBD；Phase 2 显式划出。  
3. **Type consistency:** `TargetAliyunClb` / `AliyunSlbClient` / `AliyunClbProvider.deploy` 在 Task 1→3→5 命名一致。

---

## 执行说明

计划路径：`qiniu-cert-autorenew/docs/superpowers/plans/2026-08-20-aliyun-clb-cert-extension.md`  
（副本建议同步到 `tools/.cursor/plans/` 便于 Cursor UI 打开。）
