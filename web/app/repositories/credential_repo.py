"""凭证与配置档仓储。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import DeployProfile, UserCredential


def list_credentials(db: Session, user_id: int) -> list[UserCredential]:
    return list(
        db.scalars(
            select(UserCredential)
            .where(UserCredential.user_id == user_id)
            .order_by(UserCredential.provider, UserCredential.name)
        )
    )


def get_credential(
    db: Session, cred_id: int, user_id: int
) -> UserCredential | None:
    return db.scalar(
        select(UserCredential).where(
            UserCredential.id == cred_id, UserCredential.user_id == user_id
        )
    )


def save_credential(db: Session, cred: UserCredential) -> UserCredential:
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


def delete_credential(db: Session, cred: UserCredential) -> None:
    db.delete(cred)
    db.commit()


def credential_in_use(db: Session, cred_id: int) -> bool:
    dns = db.scalar(
        select(DeployProfile.id).where(DeployProfile.dns_credential_id == cred_id).limit(1)
    )
    if dns:
        return True
    dep = db.scalar(
        select(DeployProfile.id)
        .where(DeployProfile.deploy_credential_id == cred_id)
        .limit(1)
    )
    return dep is not None


def list_profiles(db: Session, user_id: int) -> list[DeployProfile]:
    return list(
        db.scalars(
            select(DeployProfile)
            .options(
                joinedload(DeployProfile.dns_credential),
                joinedload(DeployProfile.deploy_credential),
            )
            .where(DeployProfile.user_id == user_id)
            .order_by(DeployProfile.name)
        )
    )


def get_profile(db: Session, profile_id: int, user_id: int) -> DeployProfile | None:
    return db.scalar(
        select(DeployProfile)
        .options(
            joinedload(DeployProfile.dns_credential),
            joinedload(DeployProfile.deploy_credential),
        )
        .where(DeployProfile.id == profile_id, DeployProfile.user_id == user_id)
    )


def save_profile(db: Session, profile: DeployProfile) -> DeployProfile:
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def delete_profile(db: Session, profile: DeployProfile) -> None:
    db.delete(profile)
    db.commit()


def profile_in_use(db: Session, profile_id: int) -> bool:
    from app.models import Certificate

    row = db.scalar(
        select(Certificate.id).where(Certificate.profile_id == profile_id).limit(1)
    )
    return row is not None
