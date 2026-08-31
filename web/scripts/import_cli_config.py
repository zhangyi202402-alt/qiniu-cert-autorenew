#!/usr/bin/env python3
"""把仓库根目录的 CLI config.yaml（+ .env 密钥）导入 Web 库。

用法（在仓库根或 web/ 下）::

    # 宿主机（MySQL 映射 3307）
    cd web
    PYTHONPATH=..:. \\
      DATABASE_URL='mysql+pymysql://qcert:secret@127.0.0.1:3307/qiniu_cert_web?charset=utf8mb4' \\
      PROJECT_ROOT=.. WEB_DATA_ROOT=../.local/web \\
      ../.venv/bin/python scripts/import_cli_config.py \\
        --email zhangyi@kalading.com

    # 或容器内（已挂载 /app）
    docker compose -f docker-compose.web.yml exec -T web \\
      python /app/web/scripts/import_cli_config.py --email zhangyi@kalading.com

幂等：同名凭证 / 配置档 / 证书已存在则跳过（可用 --force-update-creds 轮换密钥）。
不会打印 AccessKey / Secret。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

# --- path bootstrap ---
_WEB = Path(__file__).resolve().parents[1]
_ROOT = _WEB.parent
for p in (_ROOT, _WEB):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        # 已有非空环境变量优先（便于覆盖 DATABASE_URL）
        if key and not os.environ.get(key):
            os.environ[key] = val


def _expand_env(value: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1), m.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, value)


def _expand(obj):
    if isinstance(obj, str):
        return _expand_env(obj)
    if isinstance(obj, dict):
        return {k: _expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand(v) for v in obj]
    return obj


def _mask(s: str) -> str:
    if not s:
        return "(empty)"
    return f"len={len(s)}"


def _require_env(*names: str) -> str:
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v and not v.startswith("${"):
            return v
    raise SystemExit(f"缺少环境变量（试过 {', '.join(names)}）")


def _load_config(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _expand(raw)


def _deploy_type_of(cert: dict) -> str:
    targets = cert.get("targets") or []
    if any(isinstance(t, dict) and t.get("type") == "aliyun_clb" for t in targets):
        return "aliyun_clb"
    if cert.get("qiniu_cdn_domains"):
        return "qiniu_cdn"
    raise ValueError(f"证书 {cert.get('name')} 无法判断部署类型（无 targets/qiniu_cdn_domains）")


def _deploy_targets(cert: dict, deploy_type: str) -> list[dict]:
    if deploy_type == "qiniu_cdn":
        domains = [str(d).strip().lower().rstrip(".") for d in (cert.get("qiniu_cdn_domains") or [])]
        domains = [d for d in domains if d]
        if not domains:
            raise ValueError(f"{cert.get('name')}: qiniu_cdn_domains 为空")
        https = cert.get("https") or {}
        return [{"type": "qiniu_cdn", "domains": domains, "https": https}]
    targets = []
    for t in cert.get("targets") or []:
        if not isinstance(t, dict) or t.get("type") != "aliyun_clb":
            continue
        targets.append(
            {
                "type": "aliyun_clb",
                "region_id": t["region_id"],
                "load_balancer_id": t["load_balancer_id"],
                "listener_port": int(t.get("listener_port") or 443),
                "domain_extensions": list(t.get("domain_extensions") or []),
                "probe_host": t.get("probe_host"),
            }
        )
    if not targets:
        raise ValueError(f"{cert.get('name')}: 无 aliyun_clb targets")
    return targets


def _suggested_from_targets(targets: list[dict]) -> list[dict]:
    return targets


def _profile_name(dns_provider: str, deploy_type: str) -> str:
    return f"{dns_provider}__{deploy_type}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import CLI config.yaml into Web DB")
    parser.add_argument(
        "--config",
        type=Path,
        default=_ROOT / "config.yaml",
        help="CLI config.yaml 路径",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("IMPORT_USER_EMAIL", "zhangyi@kalading.com"),
        help="目标 Web 用户邮箱（须已注册）",
    )
    parser.add_argument(
        "--skip-disabled",
        action="store_true",
        help="跳过 config 里 enabled: false 的证书",
    )
    parser.add_argument(
        "--force-update-creds",
        action="store_true",
        help="同名凭证已存在时用 .env 密钥覆盖密文",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印计划，不写库",
    )
    args = parser.parse_args()

    # web/.env 先于根 .env：密钥在根 .env；WEB_MASTER_KEY 在 web/.env
    _load_dotenv(_WEB / ".env")
    _load_dotenv(_ROOT / ".env")

    # 宿主机默认把 docker 内网 host 改成映射口（可用环境变量覆盖）
    db_url = os.environ.get("DATABASE_URL", "")
    if "@mysql:3306" in db_url and not os.environ.get("IMPORT_KEEP_DOCKER_DB"):
        os.environ["DATABASE_URL"] = db_url.replace("@mysql:3306", "@127.0.0.1:3307")
        print(f"[env] DATABASE_URL → 127.0.0.1:3307（宿主机）")

    os.environ.setdefault("PROJECT_ROOT", str(_ROOT))
    os.environ.setdefault("WEB_DATA_ROOT", str(_ROOT / ".local" / "web"))

    # 清掉 settings 缓存（若曾被导入）
    from app import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    settings = settings_mod.get_settings()

    if not args.config.is_file():
        raise SystemExit(f"找不到配置: {args.config}")

    cfg = _load_config(args.config)
    acme = cfg.get("acme") or {}
    acme_email = str(acme.get("email") or args.email)
    renew_days = int(acme.get("renew_days") or settings.default_renew_days)

    # 密钥：DNS 阿里与 CLB 阿里可能是两套 AK
    secrets = {
        "aliyun-dns": (
            "aliyun",
            _require_env("Ali_Key", "ALIYUN_AK"),
            _require_env("Ali_Secret", "ALIYUN_SK"),
            "cn-hangzhou",
        ),
        "aliyun-clb": (
            "aliyun",
            _require_env("ALIYUN_AK", "Ali_Key"),
            _require_env("ALIYUN_SK", "Ali_Secret"),
            "cn-hangzhou",
        ),
        "tencent-dns": (
            "tencent",
            _require_env("Tencent_SecretId", "TENCENT_SECRET_ID"),
            _require_env("Tencent_SecretKey", "TENCENT_SECRET_KEY"),
            "cn-hangzhou",
        ),
        "qiniu-cdn": (
            "qiniu",
            _require_env("QINIU_AK"),
            _require_env("QINIU_SK"),
            "cn-hangzhou",
        ),
    }

    print("[plan] credentials:")
    for name, (provider, ak, sk, _) in secrets.items():
        print(f"  - {name} provider={provider} ak={_mask(ak)} sk={_mask(sk)}")

    certs_cfg = list(cfg.get("certificates") or [])
    print(f"[plan] certificates in yaml: {len(certs_cfg)}")
    for c in certs_cfg:
        enabled = c.get("enabled", True)
        print(
            f"  - {c.get('name')} dns={c.get('dns_provider')} "
            f"deploy={_deploy_type_of(c)} enabled={enabled}"
        )

    if args.dry_run:
        print("[dry-run] 未写库")
        return 0

    from sqlalchemy.orm import Session

    from app.auth import hash_password  # noqa: F401 — ensure crypto deps
    from app.cert_service import CertService
    from app.credential_service import create_credential, create_profile, update_credential
    from app.database import SessionLocal
    from app.models import Certificate, DeployProfile, User, UserCredential
    from app.repositories import credential_repo, user_repo
    from app.schemas import CertCreateForm

    db: Session = SessionLocal()
    try:
        user = user_repo.get_by_email(db, args.email.strip().lower())
        if not user:
            raise SystemExit(
                f"用户不存在: {args.email}。请先在 Web 注册，或改 --email。"
            )
        print(f"[user] id={user.id} email={user.email}")

        # --- credentials ---
        cred_ids: dict[str, int] = {}
        for name, (provider, ak, sk, cas) in secrets.items():
            existing = (
                db.query(UserCredential)
                .filter(UserCredential.user_id == user.id, UserCredential.name == name)
                .one_or_none()
            )
            if existing:
                cred_ids[name] = existing.id
                if args.force_update_creds:
                    update_credential(
                        db,
                        user.id,
                        existing.id,
                        access_key=ak,
                        secret_key=sk,
                        cas_certificate_region=cas,
                        settings=settings,
                    )
                    print(f"[cred] updated {name} id={existing.id}")
                else:
                    print(f"[cred] skip exists {name} id={existing.id}")
                continue
            c = create_credential(
                db,
                user.id,
                name=name,
                provider=provider,
                access_key=ak,
                secret_key=sk,
                cas_certificate_region=cas,
                settings=settings,
            )
            cred_ids[name] = c.id
            print(f"[cred] created {name} id={c.id}")

        def dns_cred_name(dns_provider: str) -> str:
            if dns_provider == "dns_ali":
                return "aliyun-dns"
            if dns_provider == "dns_tencent":
                return "tencent-dns"
            raise ValueError(f"unsupported dns_provider: {dns_provider}")

        def deploy_cred_name(deploy_type: str) -> str:
            if deploy_type == "qiniu_cdn":
                return "qiniu-cdn"
            if deploy_type == "aliyun_clb":
                return "aliyun-clb"
            raise ValueError(f"unsupported deploy_type: {deploy_type}")

        # --- profiles (one per dns×deploy combo) ---
        profile_ids: dict[str, int] = {}
        for cert in certs_cfg:
            dns_provider = str(cert.get("dns_provider") or "")
            deploy_type = _deploy_type_of(cert)
            pname = _profile_name(dns_provider, deploy_type)
            if pname in profile_ids:
                continue
            existing = (
                db.query(DeployProfile)
                .filter(DeployProfile.user_id == user.id, DeployProfile.name == pname)
                .one_or_none()
            )
            targets = _deploy_targets(cert, deploy_type)
            if existing:
                profile_ids[pname] = existing.id
                print(f"[profile] skip exists {pname} id={existing.id}")
                continue
            defaults = {}
            if cert.get("key_type"):
                defaults["key_type"] = cert["key_type"]
            elif deploy_type == "aliyun_clb":
                defaults["key_type"] = "rsa-2048"
            p = create_profile(
                db,
                user.id,
                name=pname,
                dns_provider=dns_provider,
                dns_credential_id=cred_ids[dns_cred_name(dns_provider)],
                deploy_type=deploy_type,
                deploy_credential_id=cred_ids[deploy_cred_name(deploy_type)],
                suggested_targets_json=_suggested_from_targets(targets),
                defaults_json=defaults or None,
            )
            profile_ids[pname] = p.id
            print(f"[profile] created {pname} id={p.id}")

        # --- certificates ---
        svc = CertService(db, settings)
        for cert in certs_cfg:
            name = str(cert.get("name") or "").strip()
            enabled = bool(cert.get("enabled", True))
            if not enabled and args.skip_disabled:
                print(f"[cert] skip disabled {name}")
                continue
            existing = (
                db.query(Certificate)
                .filter(Certificate.user_id == user.id, Certificate.name == name)
                .one_or_none()
            )
            if existing:
                print(f"[cert] skip exists {name} id={existing.id}")
                continue

            dns_provider = str(cert.get("dns_provider") or "")
            deploy_type = _deploy_type_of(cert)
            pname = _profile_name(dns_provider, deploy_type)
            issue_domains = [
                str(d).strip().lower().rstrip(".") for d in (cert.get("issue_domains") or [])
            ]
            issue_domains = [d for d in issue_domains if d]
            form = CertCreateForm(
                name=name,
                acme_email=acme_email,
                profile_id=profile_ids[pname],
                issue_domains=issue_domains,
                deploy_targets=_deploy_targets(cert, deploy_type),
                renew_days=int(cert.get("renew_days") or renew_days),
            )
            # 配额
            if user.max_certificates < 20:
                user.max_certificates = 20
                user_repo.save(db, user)

            created = svc.create_certificate(user.id, form)
            if not enabled:
                created.enabled = False
                db.add(created)
                db.commit()
                db.refresh(created)
            print(
                f"[cert] created {name} id={created.id} "
                f"primary={created.primary_domain} enabled={created.enabled} "
                f"verify={created.verification_host}"
            )

        print("[done] 登录 Web 后即可在凭证 / 配置档 / 证书列表看到导入结果。")
        print("       证书仍为 unverified，需按验证页补 TXT 后再签发。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
