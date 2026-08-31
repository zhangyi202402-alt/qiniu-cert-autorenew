"""证书 / Job 仓储。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import CertJob, Certificate


def list_for_user(db: Session, user_id: int) -> list[Certificate]:
    return (
        db.query(Certificate)
        .filter(Certificate.user_id == user_id)
        .order_by(Certificate.id.desc())
        .all()
    )


def count_for_user(db: Session, user_id: int) -> int:
    return db.query(Certificate).filter(Certificate.user_id == user_id).count()


def get_for_user(db: Session, cert_id: int, user_id: int) -> Certificate | None:
    return (
        db.query(Certificate)
        .filter(Certificate.id == cert_id, Certificate.user_id == user_id)
        .one_or_none()
    )


def get(db: Session, cert_id: int) -> Certificate | None:
    return db.get(Certificate, cert_id)


def get_for_update(db: Session, cert_id: int) -> Certificate | None:
    return (
        db.query(Certificate)
        .filter(Certificate.id == cert_id)
        .with_for_update()
        .one_or_none()
    )


def create(db: Session, cert: Certificate) -> Certificate:
    db.add(cert)
    db.commit()
    db.refresh(cert)
    return cert


def save(db: Session, cert: Certificate, *, commit: bool = True) -> Certificate:
    db.add(cert)
    if commit:
        db.commit()
        db.refresh(cert)
    else:
        db.flush()
    return cert


def create_job(
    db: Session,
    certificate_id: int,
    job_type: str,
    status: str = "running",
    *,
    commit: bool = True,
) -> CertJob:
    job = CertJob(
        certificate_id=certificate_id,
        job_type=job_type,
        status=status,
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(job)
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()
    return job


def save_job(db: Session, job: CertJob, *, commit: bool = True) -> CertJob:
    db.add(job)
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()
    return job


def commit(db: Session) -> None:
    db.commit()


def latest_job(db: Session, certificate_id: int) -> CertJob | None:
    return (
        db.query(CertJob)
        .filter(CertJob.certificate_id == certificate_id)
        .order_by(CertJob.id.desc())
        .first()
    )


def list_renew_candidates(db: Session) -> list[Certificate]:
    return (
        db.query(Certificate)
        .filter(
            Certificate.enabled.is_(True),
            Certificate.verification_status == "verified",
            Certificate.status.in_(("active", "failed")),
        )
        .all()
    )


def list_verify_candidates(db: Session) -> list[Certificate]:
    return (
        db.query(Certificate)
        .filter(
            Certificate.status.in_(("active", "failed")),
            Certificate.verification_status.in_(("verified", "lost")),
        )
        .all()
    )


def list_stuck_verified_pending(db: Session) -> list[Certificate]:
    """已验证但仍 pending_verification，可补偿签发。"""
    return (
        db.query(Certificate)
        .filter(
            Certificate.enabled.is_(True),
            Certificate.verification_status == "verified",
            Certificate.status == "pending_verification",
        )
        .all()
    )


def reclaim_stale_jobs(db: Session, minutes: int = 15) -> int:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    certs = (
        db.query(Certificate)
        .filter(
            Certificate.status.in_(("issuing", "renewing")),
            Certificate.updated_at < cutoff,
        )
        .all()
    )
    for cert in certs:
        cert.status = "failed"
        cert.last_error = f"stale job reclaimed after {minutes} minutes"
    if certs:
        db.commit()
    return len(certs)
