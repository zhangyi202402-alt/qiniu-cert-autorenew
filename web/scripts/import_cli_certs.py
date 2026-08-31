#!/usr/bin/env python3
"""将 CLI acme.sh 已签发的证书迁入 Web 用户目录，避免重新签发。

用法（宿主机，MySQL 映射 3307）::

    cd web
    PYTHONPATH=..:. \\
      DATABASE_URL='mysql+pymysql://qcert:secret@127.0.0.1:3307/qiniu_cert_web?charset=utf8mb4' \\
      PROJECT_ROOT=.. WEB_DATA_ROOT=../.local/web \\
      ../.venv/bin/python scripts/import_cli_certs.py --email zhangyi@kalading.com

Docker（证书写入 web_data 卷，acme_home 为 /app/.local/web/...）::

    docker compose -f docker-compose.web.yml run --rm --no-deps \\
      -v ../.local/acme:/cli-acme:ro \\
      web python /app/web/scripts/import_cli_certs.py \\
        --email zhangyi@kalading.com --cli-acme /cli-acme

幂等：已为 active 且 fullchain 存在则跳过（--force 可覆盖）。
不会打印私钥内容。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

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
        if key and not os.environ.get(key):
            os.environ[key] = val


def _cert_basename(cert_dir: Path) -> str:
    """从目录内文件推断 acme 证书主文件名前缀（如 example.com 或 *.example.com）。"""
    for pattern in ("*.conf", "*.key"):
        for f in cert_dir.glob(pattern):
            name = f.name
            if name.endswith(".csr.conf"):
                continue
            if f.suffix == ".conf" and name.endswith(".conf"):
                return f.stem
            if f.suffix == ".key":
                return f.stem
    stem = cert_dir.name
    if stem.endswith("_ecc"):
        return stem[:-4]
    return stem


def _find_cli_cert_dir(
    cli_acme: Path,
    *,
    primary_domain: str,
    key_type: str,
    issue_domains: list[str],
) -> Path | None:
    from qiniu_cert.acme_plan import acme_cert_dir

    candidates: list[str] = [acme_cert_dir(primary_domain, key_type)]
    for d in issue_domains:
        d = str(d).strip()
        if not d or d in candidates:
            continue
        candidates.append(d)
        candidates.append(acme_cert_dir(d, key_type))
        if d.startswith("*."):
            base = d[2:]
            candidates.append(base)
            candidates.append(acme_cert_dir(base, key_type))

    seen: set[str] = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        p = cli_acme / name
        if (p / "fullchain.cer").is_file():
            return p

    for p in sorted(cli_acme.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        if (p / "fullchain.cer").is_file():
            return p
    return None


def _copy_cert_dir(
    src: Path,
    dst_acme: Path,
    target_dir_name: str,
    target_primary: str,
) -> Path:
    src_prefix = _cert_basename(src)
    dst_dir = dst_acme / target_dir_name
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    for item in sorted(src.iterdir()):
        if not item.is_file():
            continue
        if item.name in ("fullchain.cer", "ca.cer"):
            shutil.copy2(item, dst_dir / item.name)
            continue
        if src_prefix and src_prefix in item.name:
            new_name = item.name.replace(src_prefix, target_primary, 1)
        else:
            new_name = item.name
        if item.name.endswith(".conf.removed") and new_name.endswith(".conf.removed"):
            new_name = new_name[: -len(".conf.removed")] + ".conf"
        shutil.copy2(item, dst_dir / new_name)
        if new_name.endswith(".key"):
            (dst_dir / new_name).chmod(0o600)
    return dst_dir


def _bootstrap_acme_home(cli_acme: Path, web_acme: Path, project_root: Path) -> None:
    web_acme.mkdir(parents=True, exist_ok=True)
    for name in ("acme.sh", "account.conf", "acme.sh.env"):
        src = cli_acme / name
        dst = web_acme / name
        if src.is_file() and not dst.is_file():
            shutil.copy2(src, dst)
            if name == "acme.sh":
                dst.chmod(0o755)
    for dirname in ("ca", "dnsapi"):
        src = cli_acme / dirname
        dst = web_acme / dirname
        if src.is_dir() and not dst.exists():
            shutil.copytree(src, dst)

    deploy_dir = web_acme / "deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    scripts = project_root / "scripts"
    for name in ("qiniu_wrapper.sh", "clb_wrapper.sh"):
        target = scripts / name
        link = deploy_dir / name
        if not target.is_file():
            continue
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)


def _expected_acme_home(settings, user_id: int, cert_id: int) -> Path:
    return (settings.web_data_root / str(user_id) / str(cert_id) / "acme").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import CLI-issued certs into Web user acme_home")
    parser.add_argument("--email", default=os.environ.get("IMPORT_USER_EMAIL", "zhangyi@kalading.com"))
    parser.add_argument(
        "--cli-acme",
        type=Path,
        default=None,
        help="CLI acme.sh 目录（默认 PROJECT_ROOT/.local/acme）",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="已 active 也重新复制并更新")
    parser.add_argument("--include-disabled", action="store_true", help="包含 enabled=0 的证书")
    args = parser.parse_args()

    _load_dotenv(_WEB / ".env")
    _load_dotenv(_ROOT / ".env")

    db_url = os.environ.get("DATABASE_URL", "")
    if "@mysql:3306" in db_url and not os.environ.get("IMPORT_KEEP_DOCKER_DB"):
        os.environ["DATABASE_URL"] = db_url.replace("@mysql:3306", "@127.0.0.1:3307")
        print("[env] DATABASE_URL → 127.0.0.1:3307（宿主机）")

    os.environ.setdefault("PROJECT_ROOT", str(_ROOT))
    os.environ.setdefault("WEB_DATA_ROOT", str(_ROOT / ".local" / "web"))

    from app import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    settings = settings_mod.get_settings()

    cli_acme = (args.cli_acme or (settings.project_root / ".local" / "acme")).resolve()
    if not cli_acme.is_dir():
        raise SystemExit(f"找不到 CLI acme 目录: {cli_acme}")

    from sqlalchemy.orm import Session

    from app.acme_runner import AcmeRunner
    from app.database import SessionLocal
    from app.models import CertJob, Certificate
    from app.repositories import cert_repo, user_repo
    from qiniu_cert.acme_plan import acme_cert_dir

    db: Session = SessionLocal()
    runner = AcmeRunner(settings)
    try:
        user = user_repo.get_by_email(db, args.email.strip().lower())
        if not user:
            raise SystemExit(f"用户不存在: {args.email}")

        certs = (
            db.query(Certificate)
            .filter(Certificate.user_id == user.id)
            .order_by(Certificate.id)
            .all()
        )
        if not certs:
            print("[warn] 该用户尚无证书记录，请先运行 import_cli_config.py")
            return 1

        print(f"[user] id={user.id} email={user.email}")
        print(f"[cli]  {cli_acme}")

        migrated = 0
        for cert in certs:
            if not cert.enabled and not args.include_disabled:
                print(f"[skip] {cert.name} (disabled，加 --include-disabled 可导入)")
                continue

            web_acme = _expected_acme_home(settings, user.id, cert.id)
            target_dir = acme_cert_dir(cert.primary_domain, cert.key_type)
            chain = web_acme / target_dir / "fullchain.cer"

            if cert.status == "active" and chain.is_file() and not args.force:
                print(f"[skip] {cert.name} 已 active 且证书文件存在")
                continue

            src = _find_cli_cert_dir(
                cli_acme,
                primary_domain=cert.primary_domain,
                key_type=cert.key_type,
                issue_domains=list(cert.issue_domains or []),
            )
            if not src:
                print(f"[miss] {cert.name} 在 CLI acme 中未找到 fullchain.cer")
                continue

            print(
                f"[plan] {cert.name} id={cert.id}\n"
                f"       CLI: {src.name}/ → Web: {web_acme}/{target_dir}/\n"
                f"       primary={cert.primary_domain} key_type={cert.key_type}"
            )

            if args.dry_run:
                continue

            _bootstrap_acme_home(cli_acme, web_acme, settings.project_root)
            _copy_cert_dir(src, web_acme, target_dir, cert.primary_domain)

            expires = runner.parse_expires_at(web_acme, cert.primary_domain, cert.key_type)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            cert.acme_home = str(web_acme)
            cert.status = "active"
            cert.verification_status = "verified"
            cert.verified_at = cert.verified_at or now
            cert.last_verification_at = now
            cert.expires_at = expires
            cert.last_error = None
            cert.state_json = {**(cert.state_json or {}), "cli_imported": True}
            cert_repo.save(db, cert)

            job = CertJob(
                certificate_id=cert.id,
                job_type="import",
                status="success",
                log_tail="import_cli_certs.py: migrated existing CLI certificate",
                started_at=now,
                finished_at=now,
            )
            db.add(job)
            db.commit()

            exp_s = expires.isoformat(sep=" ", timespec="seconds") if expires else "?"
            print(f"[done] {cert.name} expires_at={exp_s} acme_home={cert.acme_home}")
            migrated += 1

        if args.dry_run:
            print("[dry-run] 未写库、未复制文件")
        else:
            print(f"[summary] 迁移 {migrated} 张证书；Web 列表应显示「正常 / 已验证 / 有效期」。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
