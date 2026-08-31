"""测试辅助：创建通用凭证 + 配置档。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.credential_service import create_credential, create_profile
from app.models import DeployProfile
from app.settings import Settings


def seed_ali_qiniu_profile(
    db: Session, user_id: int, settings: Settings, *, name: str = "cdn-default"
) -> DeployProfile:
    ali = create_credential(
        db,
        user_id,
        name="ali-main",
        provider="aliyun",
        access_key="AK",
        secret_key="ASK",
        settings=settings,
    )
    qn = create_credential(
        db,
        user_id,
        name="qiniu-main",
        provider="qiniu",
        access_key="QAK",
        secret_key="QSK",
        settings=settings,
    )
    return create_profile(
        db,
        user_id,
        name=name,
        dns_provider="dns_ali",
        dns_credential_id=ali.id,
        deploy_type="qiniu_cdn",
        deploy_credential_id=qn.id,
    )
