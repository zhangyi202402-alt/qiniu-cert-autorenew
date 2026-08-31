"""证书签发 / 续签编排与状态机。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.acme_runner import AcmeRunner
from app.compat import validate_deploy_targets
from app.config_builder import ConfigBuilder, CredentialsNotConfigured, cert_ready_for_issue
from app.crypto import sanitize_error
from app.file_lock import LockBusy, file_lock
from app.models import Certificate
from app.ownership_service import OwnershipService
from app.repositories import cert_repo, credential_repo, user_repo
from app.schemas import CertCreateForm, CertUpdateForm, primary_domain_of
from app.settings import Settings, get_settings
from qiniu_cert.acme_plan import sync_renew_days

logger = logging.getLogger(__name__)


class OwnershipError(Exception):
    pass


class CredentialsError(Exception):
    pass


def _key_type_for_profile(profile, requested: str | None = None) -> str:
    key_type = "rsa-2048" if profile.deploy_type == "aliyun_clb" else "ec-256"
    defaults = profile.defaults_json or {}
    if defaults.get("key_type"):
        key_type = str(defaults["key_type"])
    if requested:
        key_type = requested
    if profile.deploy_type == "aliyun_clb" and key_type != "rsa-2048":
        raise ValueError("aliyun_clb 要求 key_type=rsa-2048")
    return key_type


def _secret_list_from_env(env: dict[str, str]) -> list[str]:
    secrets: list[str] = []
    for key, val in env.items():
        if not val or len(val) < 4:
            continue
        if any(
            k in key.upper()
            for k in ("KEY", "SECRET", "TOKEN", "PASSWORD", "SK", "AK")
        ):
            secrets.append(val)
    return secrets


class CertService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.builder = ConfigBuilder()
        self.runner = AcmeRunner(self.settings)
        self.ownership = OwnershipService()

    def create_certificate(self, user_id: int, form: CertCreateForm) -> Certificate:
        user = user_repo.get_by_id(self.db, user_id)
        if not user:
            raise ValueError("user not found")
        count = cert_repo.count_for_user(self.db, user_id)
        if count >= user.max_certificates:
            raise ValueError(f"certificate quota exceeded ({user.max_certificates})")

        profile = credential_repo.get_profile(self.db, form.profile_id, user_id)
        if not profile:
            raise ValueError("配置档不存在")

        targets = validate_deploy_targets(
            deploy_type=profile.deploy_type,
            issue_domains=form.issue_domains,
            deploy_targets=form.deploy_targets,
        )

        key_type = _key_type_for_profile(profile)

        primary = primary_domain_of(form.issue_domains)
        token = self.ownership.generate_token()
        host = self.ownership.verification_host(primary)
        cert = Certificate(
            user_id=user_id,
            profile_id=profile.id,
            name=form.name.strip(),
            primary_domain=primary,
            issue_domains=form.issue_domains,
            deploy_targets=targets,
            verification_token=token,
            verification_host=host,
            verification_status="unverified",
            status="pending_verification",
            acme_home="pending",
            enabled=True,
            renew_days=form.renew_days,
            acme_email=form.acme_email.strip(),
            key_type=key_type,
        )
        cert = cert_repo.create(self.db, cert)
        acme_home = (
            self.settings.web_data_root / str(user_id) / str(cert.id) / "acme"
        )
        acme_home.mkdir(parents=True, exist_ok=True)
        cert.acme_home = str(acme_home.resolve())
        return cert_repo.save(self.db, cert)

    def update_certificate(
        self, cert_id: int, user_id: int, form: CertUpdateForm
    ) -> Certificate:
        """改绑配置档 / 域名 / 部署目标；primary 变更则重置归属。"""
        cert = cert_repo.get_for_user(self.db, cert_id, user_id)
        if not cert:
            raise ValueError("certificate not found")
        if cert.status in ("issuing", "renewing"):
            raise ValueError("job already running")

        profile = credential_repo.get_profile(self.db, form.profile_id, user_id)
        if not profile:
            raise ValueError("配置档不存在")

        targets = validate_deploy_targets(
            deploy_type=profile.deploy_type,
            issue_domains=form.issue_domains,
            deploy_targets=form.deploy_targets,
        )
        key_type = _key_type_for_profile(profile)
        new_primary = primary_domain_of(form.issue_domains)
        old_primary = cert.primary_domain

        cert.name = form.name.strip()
        cert.acme_email = form.acme_email.strip()
        cert.renew_days = form.renew_days
        cert.profile_id = profile.id
        cert.issue_domains = form.issue_domains
        cert.deploy_targets = targets
        cert.key_type = key_type
        cert.primary_domain = new_primary

        if new_primary != old_primary:
            cert.verification_token = self.ownership.generate_token()
            cert.verification_host = self.ownership.verification_host(new_primary)
            cert.verification_status = "unverified"
            cert.verified_at = None
            if cert.status in ("active", "failed", "disabled"):
                cert.status = "pending_verification"
        # primary 不变：保持原 verification_status（targets 已由 validate 保证覆盖）

        return cert_repo.save(self.db, cert)

    def issue_certificate(self, cert_id: int, *, job_type: str = "issue") -> None:
        try:
            cert = cert_repo.get(self.db, cert_id)
            if not cert:
                logger.error("certificate %s not found", cert_id)
                return
            if not cert.acme_home or cert.acme_home == "pending":
                self._fail_cert(cert_id, "acme_home not ready", job_type=job_type)
                return
            lock_path = Path(cert.acme_home) / ".lock"
            try:
                with file_lock(lock_path, blocking=False):
                    self._issue_locked(cert_id, job_type=job_type)
            except LockBusy:
                logger.warning("cert %s lock busy, skip", cert_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("issue_certificate outer failure cert_id=%s", cert_id)
            self._fail_cert(cert_id, sanitize_error(str(exc)), job_type=job_type)

    def _fail_cert(
        self, cert_id: int, message: str, *, job_type: str = "issue"
    ) -> None:
        try:
            self.db.rollback()
        except Exception:  # noqa: BLE001
            pass
        cert = cert_repo.get(self.db, cert_id)
        if not cert:
            return
        if cert.status in ("issuing", "renewing", "pending_verification"):
            cert.status = "failed"
            cert.last_error = message[:2000]
            cert_repo.save(self.db, cert)

    def _issue_locked(self, cert_id: int, *, job_type: str) -> None:
        cert = cert_repo.get_for_update(self.db, cert_id)
        if not cert:
            return
        profile = credential_repo.get_profile(self.db, cert.profile_id, cert.user_id)
        if cert.verification_status != "verified":
            raise OwnershipError("domain ownership not verified")
        if not cert_ready_for_issue(cert, profile):
            raise CredentialsError("certificate profile or deploy targets incomplete")
        if cert.status in ("issuing", "renewing"):
            self.db.rollback()
            return

        old_expires = cert.expires_at
        cert.status = "issuing" if job_type in ("issue", "retry") else "renewing"
        job = cert_repo.create_job(
            self.db, cert_id, job_type, "running", commit=False
        )
        cert_repo.commit(self.db)
        self.db.refresh(cert)
        self.db.refresh(job)

        result_stdout = ""
        result_stderr = ""
        secret_values: list[str] = []
        try:
            runtime = self.builder.build(
                cert, self.settings, db=self.db, profile=profile
            )
            secret_values = _secret_list_from_env(runtime.env)
            self.runner.ensure_installed(runtime.acme_home, cert.acme_email)
            self.runner.setup_deploy_hooks(runtime.acme_home)
            if job_type == "renew":
                result = self.runner.renew_cron(runtime)
            else:
                result = self.runner.issue(
                    runtime, force=(job_type == "retry")
                )
            result_stdout = result.stdout
            result_stderr = result.stderr
            if not result.success:
                raise RuntimeError(result.stderr or result.stdout or "acme failed")

            try:
                sync_renew_days(runtime.config_path, runtime.acme_home)
            except Exception:  # noqa: BLE001
                logger.exception("sync_renew_days failed")

            expires = self.runner.parse_expires_at(
                runtime.acme_home, cert.primary_domain, cert.key_type
            )
            state = self.builder.read_state_to_db(runtime.state_path)

            if job_type == "renew" and old_expires and expires and expires <= old_expires:
                cert.status = "active"
                cert.expires_at = expires or old_expires
                cert.state_json = state or cert.state_json
                cert.last_error = None
                job.status = "success"
                job.log_tail = "acme cron ok (no renewal needed)"
            else:
                cert.status = "active"
                cert.expires_at = expires
                cert.state_json = state
                cert.last_error = None
                job.status = "success"
        except Exception as exc:  # noqa: BLE001
            cert.status = "failed"
            cert.last_error = sanitize_error(str(exc), secret_values)[:2000]
            job.status = "failed"
            job.log_tail = sanitize_error(
                (result_stdout + "\n" + result_stderr)[-8192:],
                secret_values,
            )
            logger.exception("issue/renew failed cert_id=%s", cert_id)
        finally:
            job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            cert_repo.save_job(self.db, job)
            cert_repo.save(self.db, cert)

    def renew_certificate(self, cert_id: int) -> None:
        cert = cert_repo.get(self.db, cert_id)
        if not cert or not cert.enabled:
            return
        result = self.ownership.verify_certificate(self.db, cert_id)
        cert = cert_repo.get(self.db, cert_id)
        if not cert:
            return
        if not result.ok or cert.verification_status != "verified":
            cert.last_error = "ownership verification lost; renew skipped"
            cert_repo.save(self.db, cert)
            return
        self.issue_certificate(cert_id, job_type="renew")

    def retry(self, cert_id: int, user_id: int) -> Certificate:
        cert = cert_repo.get_for_user(self.db, cert_id, user_id)
        if not cert:
            raise ValueError("certificate not found")
        if cert.verification_status != "verified":
            raise OwnershipError("domain ownership not verified")
        profile = credential_repo.get_profile(self.db, cert.profile_id, user_id)
        if not cert_ready_for_issue(cert, profile):
            raise CredentialsError("configure profile and deploy targets first")
        if cert.status in ("issuing", "renewing"):
            raise ValueError("job already running")
        return cert

    def toggle(self, cert_id: int, user_id: int) -> Certificate:
        cert = cert_repo.get_for_user(self.db, cert_id, user_id)
        if not cert:
            raise ValueError("certificate not found")
        cert.enabled = not cert.enabled
        if not cert.enabled:
            cert.status = "disabled"
        elif cert.status == "disabled":
            cert.status = (
                "active"
                if cert.expires_at
                else "pending_verification"
            )
        return cert_repo.save(self.db, cert)

    def get_status_json(self, cert_id: int, user_id: int) -> dict:
        cert = cert_repo.get_for_user(self.db, cert_id, user_id)
        if not cert:
            raise ValueError("certificate not found")
        job = cert_repo.latest_job(self.db, cert_id)
        return {
            "id": cert.id,
            "status": cert.status,
            "verification_status": cert.verification_status,
            "expires_at": cert.expires_at.isoformat() + "Z" if cert.expires_at else None,
            "last_error": cert.last_error,
            "last_job": (
                {
                    "job_type": job.job_type,
                    "status": job.status,
                    "started_at": job.started_at.isoformat() + "Z",
                }
                if job
                else None
            ),
        }
