"""DB 证书 + 配置档 + 凭证 → 临时 config.yaml + env。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.compat import DNS_ENV_MAP
from app.crypto import CryptoError, decrypt, master_key_bytes
from app.models import Certificate, DeployProfile, UserCredential
from app.repositories import credential_repo
from app.settings import Settings


class CredentialsNotConfigured(Exception):
    pass


@dataclass
class RuntimeConfig:
    config_path: Path
    acme_home: Path
    state_path: Path
    log_path: Path
    env: dict[str, str]
    work_dir: Path


def _decrypt_secret(cred: UserCredential, key: bytes) -> dict:
    try:
        return json.loads(decrypt(cred.secret_enc, key))
    except (CryptoError, json.JSONDecodeError) as exc:
        raise CredentialsNotConfigured("failed to decrypt credential") from exc


class ConfigBuilder:
    def build(
        self,
        cert: Certificate,
        settings: Settings,
        *,
        db: Session | None = None,
        profile: DeployProfile | None = None,
    ) -> RuntimeConfig:
        if db is not None and profile is None:
            profile = credential_repo.get_profile(db, cert.profile_id, cert.user_id)
        if profile is None:
            raise CredentialsNotConfigured("deploy profile not found")

        key = master_key_bytes(settings.web_master_key)
        dns_cred = profile.dns_credential
        dep_cred = profile.deploy_credential
        if dns_cred is None or dep_cred is None:
            if db is None:
                raise CredentialsNotConfigured("credentials not loaded")
            dns_cred = credential_repo.get_credential(
                db, profile.dns_credential_id, cert.user_id
            )
            dep_cred = credential_repo.get_credential(
                db, profile.deploy_credential_id, cert.user_id
            )
        if not dns_cred or not dep_cred:
            raise CredentialsNotConfigured("profile credentials missing")

        dns_secret = _decrypt_secret(dns_cred, key)
        dep_secret = _decrypt_secret(dep_cred, key)
        provider = profile.dns_provider
        if provider not in DNS_ENV_MAP:
            raise CredentialsNotConfigured(f"unsupported dns_provider: {provider}")

        work_dir = Path(cert.acme_home).parent
        acme_home = Path(cert.acme_home)
        state_path = work_dir / "state" / "state.json"
        log_path = work_dir / "log" / "acme.log"
        config_path = work_dir / "config.yaml"

        work_dir.mkdir(parents=True, exist_ok=True)
        acme_home.mkdir(parents=True, exist_ok=True)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        dns_env = DNS_ENV_MAP[provider]
        defaults = profile.defaults_json or {}
        cert_entry: dict = {
            "name": cert.name,
            "issue_domains": list(cert.issue_domains),
            "dns_provider": provider,
            "dns_env": dns_env,
            "key_type": cert.key_type,
        }

        env: dict[str, str] = {
            "QINIU_CERT_CONFIG": str(config_path),
            "PYTHONPATH": str(settings.project_root),
            "HOME": str(acme_home),
        }

        payload: dict = {
            "acme": {
                "email": cert.acme_email,
                "ca": settings.acme_ca,
                "key_type": cert.key_type,
                "renew_days": cert.renew_days,
            },
            "certificates": [cert_entry],
            "paths": {"state_file": str(state_path)},
            "deploy": {
                "probe_retries": 5,
                "probe_interval_sec": 30,
                "old_cert_cleanup_days": 7,
                "min_valid_days": 1,
            },
        }

        if profile.deploy_type == "qiniu_cdn":
            domains: list[str] = []
            https = defaults.get("https") or {
                "force_https": False,
                "http2_enable": True,
            }
            for t in cert.deploy_targets or []:
                if t.get("type") == "qiniu_cdn":
                    domains.extend(t.get("domains") or [])
                    if t.get("https"):
                        https = t["https"]
            cert_entry["qiniu_cdn_domains"] = domains
            cert_entry["https"] = https
            payload["qiniu"] = {
                "access_key": "${QINIU_AK}",
                "secret_key": "${QINIU_SK}",
            }
            env["QINIU_AK"] = str(dep_secret.get("access_key") or "")
            env["QINIU_SK"] = str(dep_secret.get("secret_key") or "")
        elif profile.deploy_type == "aliyun_clb":
            targets = []
            for t in cert.deploy_targets or []:
                if t.get("type") != "aliyun_clb":
                    continue
                targets.append(
                    {
                        "type": "aliyun_clb",
                        "region_id": t["region_id"],
                        "load_balancer_id": t["load_balancer_id"],
                        "listener_port": t.get("listener_port", 443),
                        "domain_extensions": t.get("domain_extensions") or [],
                        "probe_host": t.get("probe_host"),
                    }
                )
            cert_entry["targets"] = targets
            cas_region = (
                dep_secret.get("cas_certificate_region")
                or defaults.get("cas_certificate_region")
                or "cn-hangzhou"
            )
            payload["aliyun"] = {
                "access_key": "${ALIYUN_AK}",
                "secret_key": "${ALIYUN_SK}",
                "cas_certificate_region": cas_region,
            }
            payload["qiniu"] = {"access_key": "", "secret_key": ""}
            env["ALIYUN_AK"] = str(dep_secret.get("access_key") or "")
            env["ALIYUN_SK"] = str(dep_secret.get("secret_key") or "")
        else:
            raise CredentialsNotConfigured(
                f"unsupported deploy_type: {profile.deploy_type}"
            )

        # DNS env：aliyun DNS 与 aliyun 部署可能共用密钥形态
        if provider == "dns_ali":
            env["Ali_Key"] = str(
                dns_secret.get("Ali_Key")
                or dns_secret.get("access_key")
                or ""
            )
            env["Ali_Secret"] = str(
                dns_secret.get("Ali_Secret")
                or dns_secret.get("secret_key")
                or ""
            )
        elif provider == "dns_tencent":
            env["Tencent_SecretId"] = str(
                dns_secret.get("Tencent_SecretId")
                or dns_secret.get("secret_id")
                or ""
            )
            env["Tencent_SecretKey"] = str(
                dns_secret.get("Tencent_SecretKey")
                or dns_secret.get("secret_key")
                or ""
            )

        config_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        return RuntimeConfig(
            config_path=config_path,
            acme_home=acme_home,
            state_path=state_path,
            log_path=log_path,
            env=env,
            work_dir=work_dir,
        )

    def read_state_to_db(self, state_path: Path) -> dict:
        if not state_path.is_file():
            return {}
        return json.loads(state_path.read_text(encoding="utf-8"))


def cert_ready_for_issue(cert: Certificate, profile: DeployProfile | None) -> bool:
    if not profile:
        return False
    if cert.verification_status != "verified":
        return False
    if not cert.deploy_targets:
        return False
    return True
