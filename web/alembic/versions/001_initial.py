"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("qiniu_ak_enc", sa.Text(), nullable=True),
        sa.Column("qiniu_sk_enc", sa.Text(), nullable=True),
        sa.Column("dns_provider", sa.String(length=32), nullable=True),
        sa.Column("dns_secret_enc", sa.Text(), nullable=True),
        sa.Column("max_certificates", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uk_users_email"),
    )
    op.create_table(
        "certificates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("primary_domain", sa.String(length=255), nullable=False),
        sa.Column("issue_domains", sa.JSON(), nullable=False),
        sa.Column("cdn_domains", sa.JSON(), nullable=False),
        sa.Column("verification_token", sa.String(length=64), nullable=False),
        sa.Column("verification_host", sa.String(length=255), nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="unverified"),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("last_verification_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending_verification"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("acme_home", sa.String(length=512), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("renew_days", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("acme_email", sa.String(length=255), nullable=False),
        sa.Column("key_type", sa.String(length=16), nullable=False, server_default="ec-256"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_cert_user", "certificates", ["user_id"])
    op.create_index(
        "idx_cert_verification",
        "certificates",
        ["verification_status", "status"],
    )
    op.create_table(
        "cert_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("certificate_id", sa.BigInteger(), nullable=False),
        sa.Column("job_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("log_tail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["certificate_id"], ["certificates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_job_cert", "cert_jobs", ["certificate_id"])


def downgrade() -> None:
    op.drop_table("cert_jobs")
    op.drop_index("idx_cert_verification", table_name="certificates")
    op.drop_index("idx_cert_user", table_name="certificates")
    op.drop_table("certificates")
    op.drop_table("users")
