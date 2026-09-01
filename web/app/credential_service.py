"""通用凭证与配置档业务。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.compat import assert_deploy_compatible, assert_dns_compatible
from app.crypto import encrypt, master_key_bytes
from app.models import DeployProfile, UserCredential
from app.repositories import credential_repo
from app.settings import Settings, get_settings

PROVIDERS = frozenset({"aliyun", "tencent", "qiniu"})
DNS_PROVIDERS = frozenset({"dns_ali", "dns_tencent"})
DEPLOY_TYPES = frozenset({"qiniu_cdn", "aliyun_clb", "aliyun_cdn"})


def _master(settings: Settings | None = None) -> bytes:
    settings = settings or get_settings()
    return master_key_bytes(settings.web_master_key)


def _secret_payload(
    provider: str,
    access_key: str,
    secret_key: str,
    cas_certificate_region: str = "cn-hangzhou",
) -> dict:
    if provider == "aliyun":
        return {
            "access_key": access_key.strip(),
            "secret_key": secret_key.strip(),
            "cas_certificate_region": cas_certificate_region.strip() or "cn-hangzhou",
        }
    if provider == "tencent":
        return {
            "secret_id": access_key.strip(),
            "secret_key": secret_key.strip(),
        }
    return {
        "access_key": access_key.strip(),
        "secret_key": secret_key.strip(),
    }


def create_credential(
    db: Session,
    user_id: int,
    *,
    name: str,
    provider: str,
    access_key: str,
    secret_key: str,
    cas_certificate_region: str = "cn-hangzhou",
    settings: Settings | None = None,
) -> UserCredential:
    name = name.strip()
    provider = provider.strip()
    if not name:
        raise ValueError("名称不能为空")
    if provider not in PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")
    if not access_key.strip() or not secret_key.strip():
        raise ValueError("密钥不能为空")

    key = _master(settings)
    cred = UserCredential(
        user_id=user_id,
        name=name,
        provider=provider,
        secret_enc=encrypt(
            json.dumps(
                _secret_payload(
                    provider, access_key, secret_key, cas_certificate_region
                )
            ),
            key,
        ),
    )
    try:
        return credential_repo.save_credential(db, cred)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise ValueError("名称可能重复或保存失败") from exc


def update_credential(
    db: Session,
    user_id: int,
    cred_id: int,
    *,
    name: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    cas_certificate_region: str | None = None,
    settings: Settings | None = None,
) -> UserCredential:
    """轮换密钥：未填的密钥字段保持不变；若填了 access/secret 则两者都必填。"""
    from app.crypto import decrypt

    cred = credential_repo.get_credential(db, cred_id, user_id)
    if not cred:
        raise ValueError("凭证不存在")
    if name is not None and name.strip():
        cred.name = name.strip()

    key = _master(settings)
    ak = (access_key or "").strip()
    sk = (secret_key or "").strip()
    if ak or sk:
        if not ak or not sk:
            raise ValueError("更新密钥时 AccessKey 与 SecretKey 须同时填写")
        old = json.loads(decrypt(cred.secret_enc, key))
        region = (
            cas_certificate_region
            if cas_certificate_region is not None
            else old.get("cas_certificate_region", "cn-hangzhou")
        )
        cred.secret_enc = encrypt(
            json.dumps(_secret_payload(cred.provider, ak, sk, str(region))),
            key,
        )
    elif cas_certificate_region is not None and cred.provider == "aliyun":
        old = json.loads(decrypt(cred.secret_enc, key))
        old["cas_certificate_region"] = cas_certificate_region.strip() or "cn-hangzhou"
        cred.secret_enc = encrypt(json.dumps(old), key)

    try:
        return credential_repo.save_credential(db, cred)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise ValueError("保存失败（名称可能重复）") from exc


def delete_credential(db: Session, user_id: int, cred_id: int) -> None:
    cred = credential_repo.get_credential(db, cred_id, user_id)
    if not cred:
        raise ValueError("凭证不存在")
    if credential_repo.credential_in_use(db, cred_id):
        raise ValueError("凭证仍被配置档引用，请先修改或删除配置档")
    credential_repo.delete_credential(db, cred)


def create_profile(
    db: Session,
    user_id: int,
    *,
    name: str,
    dns_provider: str,
    dns_credential_id: int,
    deploy_type: str,
    deploy_credential_id: int,
    defaults_json: dict | None = None,
    suggested_targets_json: list | None = None,
) -> DeployProfile:
    name = name.strip()
    if not name:
        raise ValueError("名称不能为空")
    if dns_provider not in DNS_PROVIDERS:
        raise ValueError(f"unsupported dns_provider: {dns_provider}")
    if deploy_type not in DEPLOY_TYPES:
        raise ValueError(f"unsupported deploy_type: {deploy_type}")

    dns_cred = credential_repo.get_credential(db, dns_credential_id, user_id)
    dep_cred = credential_repo.get_credential(db, deploy_credential_id, user_id)
    if not dns_cred or not dep_cred:
        raise ValueError("凭证不存在或不属于当前用户")
    assert_dns_compatible(dns_provider, dns_cred.provider)
    assert_deploy_compatible(deploy_type, dep_cred.provider)

    profile = DeployProfile(
        user_id=user_id,
        name=name,
        dns_provider=dns_provider,
        dns_credential_id=dns_cred.id,
        deploy_type=deploy_type,
        deploy_credential_id=dep_cred.id,
        defaults_json=defaults_json or {},
        suggested_targets_json=suggested_targets_json,
    )
    try:
        return credential_repo.save_profile(db, profile)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise ValueError("配置档名称可能重复或保存失败") from exc


def update_profile(
    db: Session,
    user_id: int,
    profile_id: int,
    *,
    name: str | None = None,
    dns_provider: str | None = None,
    dns_credential_id: int | None = None,
    deploy_type: str | None = None,
    deploy_credential_id: int | None = None,
    defaults_json: dict | None = None,
    suggested_targets_json: list | None = None,
) -> DeployProfile:
    profile = credential_repo.get_profile(db, profile_id, user_id)
    if not profile:
        raise ValueError("配置档不存在")

    if name is not None and name.strip():
        profile.name = name.strip()
    if dns_provider is not None:
        if dns_provider not in DNS_PROVIDERS:
            raise ValueError(f"unsupported dns_provider: {dns_provider}")
        profile.dns_provider = dns_provider
    if deploy_type is not None:
        if deploy_type not in DEPLOY_TYPES:
            raise ValueError(f"unsupported deploy_type: {deploy_type}")
        profile.deploy_type = deploy_type
    if dns_credential_id is not None:
        profile.dns_credential_id = dns_credential_id
    if deploy_credential_id is not None:
        profile.deploy_credential_id = deploy_credential_id
    if defaults_json is not None:
        profile.defaults_json = defaults_json
    if suggested_targets_json is not None:
        profile.suggested_targets_json = suggested_targets_json

    dns_cred = credential_repo.get_credential(db, profile.dns_credential_id, user_id)
    dep_cred = credential_repo.get_credential(
        db, profile.deploy_credential_id, user_id
    )
    if not dns_cred or not dep_cred:
        raise ValueError("凭证不存在或不属于当前用户")
    assert_dns_compatible(profile.dns_provider, dns_cred.provider)
    assert_deploy_compatible(profile.deploy_type, dep_cred.provider)

    try:
        return credential_repo.save_profile(db, profile)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise ValueError("保存失败（名称可能重复）") from exc


def delete_profile(db: Session, user_id: int, profile_id: int) -> None:
    profile = credential_repo.get_profile(db, profile_id, user_id)
    if not profile:
        raise ValueError("配置档不存在")
    if credential_repo.profile_in_use(db, profile_id):
        raise ValueError("配置档仍被证书引用，请先修改或删除证书")
    credential_repo.delete_profile(db, profile)
