"""ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    max_certificates: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    certificates: Mapped[list[Certificate]] = relationship(back_populates="user")
    credentials: Mapped[list[UserCredential]] = relationship(back_populates="user")
    profiles: Mapped[list[DeployProfile]] = relationship(back_populates="user")


class UserCredential(Base):
    __tablename__ = "user_credentials"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uk_cred_user_name"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # aliyun|tencent|qiniu
    secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="credentials")
    dns_profiles: Mapped[list[DeployProfile]] = relationship(
        back_populates="dns_credential",
        foreign_keys="DeployProfile.dns_credential_id",
    )
    deploy_profiles: Mapped[list[DeployProfile]] = relationship(
        back_populates="deploy_credential",
        foreign_keys="DeployProfile.deploy_credential_id",
    )


class DeployProfile(Base):
    __tablename__ = "deploy_profiles"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uk_profile_user_name"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    dns_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    dns_credential_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("user_credentials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    deploy_type: Mapped[str] = mapped_column(String(32), nullable=False)  # qiniu_cdn|aliyun_cdn|aliyun_clb
    deploy_credential_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("user_credentials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    defaults_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    suggested_targets_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="profiles")
    dns_credential: Mapped[UserCredential] = relationship(
        foreign_keys=[dns_credential_id], back_populates="dns_profiles"
    )
    deploy_credential: Mapped[UserCredential] = relationship(
        foreign_keys=[deploy_credential_id], back_populates="deploy_profiles"
    )
    certificates: Mapped[list[Certificate]] = relationship(back_populates="profile")


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("deploy_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    issue_domains: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    deploy_targets: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    verification_token: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_host: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unverified"
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_verification_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending_verification"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    acme_home: Mapped[str] = mapped_column(String(512), nullable=False)
    state_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    renew_days: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    acme_email: Mapped[str] = mapped_column(String(255), nullable=False)
    key_type: Mapped[str] = mapped_column(String(16), nullable=False, default="ec-256")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="certificates")
    profile: Mapped[DeployProfile] = relationship(back_populates="certificates")
    jobs: Mapped[list[CertJob]] = relationship(back_populates="certificate")


class CertJob(Base):
    __tablename__ = "cert_jobs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    certificate_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("certificates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    log_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    certificate: Mapped[Certificate] = relationship(back_populates="jobs")
