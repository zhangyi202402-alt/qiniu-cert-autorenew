"""acme.sh 子进程封装。"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config_builder import RuntimeConfig
from app.settings import Settings
from qiniu_cert.acme_plan import (
    acme_cert_dir,
    acme_days_arg,
    build_issue_plans,
)
from qiniu_cert.config import load_config

logger = logging.getLogger(__name__)


@dataclass
class AcmeResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int


class AcmeRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_installed(self, acme_home: Path, email: str) -> None:
        acme_sh = acme_home / "acme.sh"
        if acme_sh.is_file() and os.access(acme_sh, os.X_OK):
            return
        install_sh = self.settings.project_root / "scripts" / "acme-install.sh"
        # 轻量安装：直接 clone + install，不依赖全局 config
        acme_home.mkdir(parents=True, exist_ok=True)
        clone_dir = acme_home / ".acme-src"
        if clone_dir.exists():
            subprocess.run(["rm", "-rf", str(clone_dir)], check=False)
        repo = os.environ.get(
            "ACME_GIT_REPO", "https://github.com/acmesh-official/acme.sh.git"
        )
        subprocess.run(
            ["git", "clone", "--depth", "1", repo, str(clone_dir)],
            check=True,
            timeout=120,
        )
        env = os.environ.copy()
        env["HOME"] = str(acme_home)
        subprocess.run(
            [
                "bash",
                "acme.sh",
                "--install",
                "-m",
                email,
                "--home",
                str(acme_home),
                "--force",
            ],
            cwd=str(clone_dir),
            env=env,
            check=True,
            timeout=120,
        )
        subprocess.run(["rm", "-rf", str(clone_dir)], check=False)
        # 设置默认 CA
        self._run(
            [
                str(acme_home / "acme.sh"),
                "--home",
                str(acme_home),
                "--set-default-ca",
                "--server",
                self.settings.acme_ca,
            ],
            runtime_env={"HOME": str(acme_home)},
            cwd=self.settings.project_root,
            timeout=60,
        )
        _ = install_sh  # 保留引用说明

    def setup_deploy_hooks(self, acme_home: Path) -> None:
        deploy_dir = acme_home / "deploy"
        deploy_dir.mkdir(parents=True, exist_ok=True)
        scripts = self.settings.project_root / "scripts"
        for name in ("qiniu_wrapper.sh", "clb_wrapper.sh", "cdn_wrapper.sh"):
            target = scripts / name
            link = deploy_dir / name
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(target)

    def issue(self, runtime: RuntimeConfig, *, force: bool = False) -> AcmeResult:
        from qiniu_cert.acme_plan import deploy_hook_for

        # load_config 用 os.environ 展开 ${VAR}；先合并 runtime.env
        _env_backup: dict[str, str | None] = {}
        for k, v in runtime.env.items():
            _env_backup[k] = os.environ.get(k)
            os.environ[k] = v
        try:
            config = load_config(runtime.config_path)
            plans = build_issue_plans(config)
            if not plans:
                return AcmeResult(False, "", "no issue plans", 1)
            plan = plans[0]
            days = acme_days_arg(config)
            hook = deploy_hook_for(config.certificates[0])

            # 签发前 TXT 预检（与 CLI dns_check 对齐，失败不阻断但写入日志）
            try:
                from qiniu_cert.dns_check import check_certificate

                cert_cfg = config.certificates[0]
                rows = check_certificate(cert_cfg)
                preview = "; ".join(
                    f"{host}={'|'.join(vals) if vals else '(none)'}"
                    for _, host, vals in rows
                )
                logger.info("dns_check before issue: %s", preview)
                if runtime.log_path:
                    runtime.log_path.parent.mkdir(parents=True, exist_ok=True)
                    with runtime.log_path.open("a", encoding="utf-8") as fh:
                        fh.write(f"\n=== dns_check ===\n{preview}\n")
            except Exception:  # noqa: BLE001
                logger.exception("dns_check failed (non-fatal)")

            cmd = [
                str(runtime.acme_home / "acme.sh"),
                "--home",
                str(runtime.acme_home),
                "--issue",
                "--dns",
                plan.dns_hook,
            ]
            for domain in config.certificates[0].issue_domains:
                cmd.extend(["-d", domain])
            cmd.extend(["--keylength", plan.keylength, "--days", days])
            if force:
                cmd.append("--force")

            result = self._run(
                cmd,
                runtime_env=runtime.env,
                cwd=self.settings.project_root,
                timeout=600,
                log_path=runtime.log_path,
            )
            if not result.success:
                return result

            deploy_cmd = [
                str(runtime.acme_home / "acme.sh"),
                "--home",
                str(runtime.acme_home),
                "--deploy",
                "-d",
                plan.primary_domain,
                "--deploy-hook",
                hook,
            ]
            return self._run(
                deploy_cmd,
                runtime_env=runtime.env,
                cwd=self.settings.project_root,
                timeout=600,
                log_path=runtime.log_path,
            )
        finally:
            for k, old in _env_backup.items():
                if old is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = old

    def renew_cron(self, runtime: RuntimeConfig) -> AcmeResult:
        cmd = [
            str(runtime.acme_home / "acme.sh"),
            "--cron",
            "--home",
            str(runtime.acme_home),
        ]
        return self._run(
            cmd,
            runtime_env=runtime.env,
            cwd=self.settings.project_root,
            timeout=600,
            log_path=runtime.log_path,
        )

    def parse_expires_at(
        self, acme_home: Path, primary_domain: str, key_type: str
    ) -> datetime | None:
        from cryptography import x509

        cert_dir = acme_home / acme_cert_dir(primary_domain, key_type)
        chain = cert_dir / "fullchain.cer"
        if not chain.is_file():
            return None
        pem = chain.read_bytes()
        cert = x509.load_pem_x509_certificate(pem)
        not_after = getattr(cert, "not_valid_after_utc", cert.not_valid_after)
        if not_after.tzinfo is None:
            not_after = not_after.replace(tzinfo=timezone.utc)
        return not_after.replace(tzinfo=None)

    def _run(
        self,
        cmd: list[str],
        *,
        runtime_env: dict[str, str],
        cwd: Path,
        timeout: int,
        log_path: Path | None = None,
    ) -> AcmeResult:
        env = os.environ.copy()
        env.update(runtime_env)
        env["QINIU_CERT_PYTHON"] = env.get("QINIU_CERT_PYTHON", "python3")
        pythonpath = str(self.settings.project_root)
        if env.get("PYTHONPATH"):
            env["PYTHONPATH"] = f"{pythonpath}:{env['PYTHONPATH']}"
        else:
            env["PYTHONPATH"] = pythonpath

        logger.info("acme cmd: %s", " ".join(cmd[:6]) + " ...")
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            err = (exc.stderr or "") if isinstance(exc.stderr, str) else "timeout"
            return AcmeResult(False, out, err, 124)

        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n=== {' '.join(cmd[:8])} ===\n")
                fh.write(proc.stdout or "")
                fh.write(proc.stderr or "")

        return AcmeResult(
            success=proc.returncode == 0,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )
