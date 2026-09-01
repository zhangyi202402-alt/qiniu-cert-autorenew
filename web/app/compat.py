"""DNS / 部署类型与云厂商凭证的兼容矩阵、域名覆盖校验。"""

from __future__ import annotations

DNS_PROVIDER_TO_CLOUD = {
    "dns_ali": "aliyun",
    "dns_tencent": "tencent",
}

DEPLOY_TYPE_TO_CLOUD = {
    "qiniu_cdn": "qiniu",
    "aliyun_clb": "aliyun",
    "aliyun_cdn": "aliyun",
}

DNS_ENV_MAP: dict[str, dict[str, str]] = {
    "dns_ali": {"ali_key": "Ali_Key", "ali_secret": "Ali_Secret"},
    "dns_tencent": {
        "tencent_id": "Tencent_SecretId",
        "tencent_key": "Tencent_SecretKey",
    },
}


def assert_dns_compatible(dns_provider: str, credential_provider: str) -> None:
    expected = DNS_PROVIDER_TO_CLOUD.get(dns_provider)
    if expected is None:
        raise ValueError(f"unsupported dns_provider: {dns_provider}")
    if credential_provider != expected:
        raise ValueError(
            f"{dns_provider} 只能引用 {expected} 凭证，当前为 {credential_provider}"
        )


def assert_deploy_compatible(deploy_type: str, credential_provider: str) -> None:
    expected = DEPLOY_TYPE_TO_CLOUD.get(deploy_type)
    if expected is None:
        raise ValueError(f"unsupported deploy_type: {deploy_type}")
    if credential_provider != expected:
        raise ValueError(
            f"{deploy_type} 只能引用 {expected} 凭证，当前为 {credential_provider}"
        )


def issue_domains_cover(issue_domains: list[str], host: str) -> bool:
    """issue_domains（含 *.example.com）是否覆盖 host（单层通配，对齐 LE）。"""
    host = host.lower().rstrip(".")
    for pattern in issue_domains:
        p = pattern.lower().rstrip(".")
        if p == host:
            return True
        if p.startswith("*."):
            base = p[2:]
            if host == base:
                continue
            if host.endswith("." + base):
                rest = host[: -(len(base) + 1)]
                if rest and "." not in rest:
                    return True
    return False


def validate_deploy_targets(
    *,
    deploy_type: str,
    issue_domains: list[str],
    deploy_targets: list[dict],
) -> list[dict]:
    if not deploy_targets:
        raise ValueError("至少需要一个部署目标")
    cleaned: list[dict] = []
    for raw in deploy_targets:
        if not isinstance(raw, dict):
            raise ValueError("deploy_targets 项必须是对象")
        ttype = str(raw.get("type") or "").strip()
        if ttype != deploy_type:
            raise ValueError(
                f"部署目标 type={ttype!r} 与配置档 deploy_type={deploy_type!r} 不一致"
            )
        if ttype == "qiniu_cdn":
            domains = raw.get("domains") or []
            if not isinstance(domains, list) or not domains:
                raise ValueError("qiniu_cdn 目标需要 domains 列表")
            norm = [str(d).strip().lower().rstrip(".") for d in domains]
            for d in norm:
                if not issue_domains_cover(issue_domains, d):
                    raise ValueError(f"CDN 域名 {d} 未被签发域名覆盖")
            https = raw.get("https") if isinstance(raw.get("https"), dict) else {}
            cleaned.append({"type": "qiniu_cdn", "domains": norm, "https": https})
        elif ttype == "aliyun_cdn":
            domains = raw.get("domains") or []
            if not isinstance(domains, list) or not domains:
                raise ValueError("aliyun_cdn 目标需要 domains 列表")
            norm = [str(d).strip().lower().rstrip(".") for d in domains]
            for d in norm:
                if not issue_domains_cover(issue_domains, d):
                    raise ValueError(f"CDN 域名 {d} 未被签发域名覆盖")
            https = raw.get("https") if isinstance(raw.get("https"), dict) else {}
            cleaned.append({"type": "aliyun_cdn", "domains": norm, "https": https})
        elif ttype == "aliyun_clb":
            region = str(raw.get("region_id") or "").strip()
            lb = str(raw.get("load_balancer_id") or "").strip()
            if not region or not lb:
                raise ValueError("aliyun_clb 需要 region_id 与 load_balancer_id")
            port = int(raw.get("listener_port") or 443)
            exts = raw.get("domain_extensions") or []
            if not isinstance(exts, list):
                raise ValueError("domain_extensions 须为列表")
            exts_n = [str(x).strip().lower().rstrip(".") for x in exts if str(x).strip()]
            for d in exts_n:
                if not issue_domains_cover(issue_domains, d):
                    raise ValueError(f"CLB 扩展域名 {d} 未被签发域名覆盖")
            probe = raw.get("probe_host")
            probe_n = str(probe).strip().lower().rstrip(".") if probe else None
            if probe_n and not issue_domains_cover(issue_domains, probe_n):
                raise ValueError(f"probe_host {probe_n} 未被签发域名覆盖")
            cleaned.append(
                {
                    "type": "aliyun_clb",
                    "region_id": region,
                    "load_balancer_id": lb,
                    "listener_port": port,
                    "domain_extensions": exts_n,
                    "probe_host": probe_n,
                }
            )
        else:
            raise ValueError(f"unsupported deploy target type: {ttype}")
    return cleaned
