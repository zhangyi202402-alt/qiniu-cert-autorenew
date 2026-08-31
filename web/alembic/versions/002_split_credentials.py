"""split credentials into user_credentials + deploy_profiles (B+B1)

Revision ID: 002_split_credentials
Revises: 001_initial
Create Date: 2026-08-30
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "002_split_credentials"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_credentials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("secret_enc", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uk_cred_user_name"),
    )
    op.create_index("idx_cred_user", "user_credentials", ["user_id"])

    op.create_table(
        "deploy_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("dns_provider", sa.String(length=32), nullable=False),
        sa.Column("dns_credential_id", sa.BigInteger(), nullable=False),
        sa.Column("deploy_type", sa.String(length=32), nullable=False),
        sa.Column("deploy_credential_id", sa.BigInteger(), nullable=False),
        sa.Column("defaults_json", sa.JSON(), nullable=True),
        sa.Column("suggested_targets_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dns_credential_id"], ["user_credentials.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deploy_credential_id"], ["user_credentials.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uk_profile_user_name"),
    )
    op.create_index("idx_profile_user", "deploy_profiles", ["user_id"])

    op.add_column("certificates", sa.Column("profile_id", sa.BigInteger(), nullable=True))
    op.add_column("certificates", sa.Column("deploy_targets", sa.JSON(), nullable=True))

    conn = op.get_bind()
    insp = inspect(conn)
    user_cols = {c["name"] for c in insp.get_columns("users")}
    has_old = "qiniu_ak_enc" in user_cols

    if has_old:
        users = conn.execute(
            text(
                "SELECT id, qiniu_ak_enc, qiniu_sk_enc, dns_provider, dns_secret_enc "
                "FROM users"
            )
        ).fetchall()
        for row in users:
            uid, qak, qsk, dns_prov, dns_enc = row
            if not (qak and qsk and dns_prov and dns_enc):
                continue
            # 旧 User 密文格式与新 UserCredential 不兼容，且迁移时未必能拿到同一
            # WEB_MASTER_KEY 做无损转换。有旧证书时只能清空后由用户在新 UI 重建。
            pass

        certs = conn.execute(
            text("SELECT id, user_id, cdn_domains FROM certificates")
        ).fetchall()
        for cid, uid, cdn in certs:
            domains = cdn
            if isinstance(domains, str):
                try:
                    domains = json.loads(domains)
                except json.JSONDecodeError:
                    domains = []
            targets = [{"type": "qiniu_cdn", "domains": domains or [], "https": {}}]
            conn.execute(
                text("UPDATE certificates SET deploy_targets = :t WHERE id = :id"),
                {"t": json.dumps(targets, ensure_ascii=False), "id": cid},
            )

    # 无 profile_id 的证书无法在 B+B1 下签发；旧捆绑凭据无法自动升档。
    # 破坏性：删除孤儿证书（空库无影响；有数据请先备份并手工重建配置档）。
    orphan = conn.execute(
        text("SELECT COUNT(*) FROM certificates WHERE profile_id IS NULL")
    ).scalar()
    if orphan and int(orphan) > 0:
        conn.execute(text("DELETE FROM cert_jobs"))
        conn.execute(text("DELETE FROM certificates"))

    # MySQL: alter profile_id / deploy_targets NOT NULL after backfill
    with op.batch_alter_table("certificates") as batch:
        batch.alter_column(
            "deploy_targets",
            existing_type=sa.JSON(),
            nullable=False,
            server_default=None,
        )
        # profile_id 仍可能无行；表空后加 FK
        batch.alter_column(
            "profile_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch.create_foreign_key(
            "fk_cert_profile",
            "deploy_profiles",
            ["profile_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.drop_column("cdn_domains")

    if has_old:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("qiniu_ak_enc")
            batch.drop_column("qiniu_sk_enc")
            batch.drop_column("dns_provider")
            batch.drop_column("dns_secret_enc")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("qiniu_ak_enc", sa.Text(), nullable=True))
        batch.add_column(sa.Column("qiniu_sk_enc", sa.Text(), nullable=True))
        batch.add_column(sa.Column("dns_provider", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("dns_secret_enc", sa.Text(), nullable=True))

    with op.batch_alter_table("certificates") as batch:
        batch.add_column(sa.Column("cdn_domains", sa.JSON(), nullable=True))
        batch.drop_constraint("fk_cert_profile", type_="foreignkey")
        batch.drop_column("profile_id")
        batch.drop_column("deploy_targets")

    op.drop_table("deploy_profiles")
    op.drop_table("user_credentials")
