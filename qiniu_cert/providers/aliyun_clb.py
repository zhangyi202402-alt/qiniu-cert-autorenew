"""阿里云 CLB 证书部署 provider。"""

from __future__ import annotations

import logging
import time

from qiniu_cert.cert_utils import (
    DeployError,
    assert_certificate_rsa,
    cert_covers_domain,
    ensure_rsa_private_key_pkcs1,
    tls_probe,
)
from qiniu_cert.clients.aliyun_slb import AliyunSlbClient, AliyunSlbError
from qiniu_cert.config import AppConfig, CertificateConfig, TargetAliyunClb
from qiniu_cert.state import StateStore

logger = logging.getLogger(__name__)


def clb_state_key(target: TargetAliyunClb, domain: str | None = None) -> str:
    base = f"clb:{target.region_id}:{target.load_balancer_id}:{target.listener_port}"
    if domain:
        return f"{base}:{domain}"
    return base


class AliyunClbProvider:
    """上传证书并换绑 CLB HTTPS 监听 / 扩展域名。"""

    def __init__(self, config: AppConfig, state: StateStore | None = None) -> None:
        self.config = config
        if not config.aliyun_ak or not config.aliyun_sk:
            raise DeployError("aliyun access_key/secret_key required for CLB deploy")
        self.client = AliyunSlbClient(config.aliyun_ak, config.aliyun_sk)
        self.state = state or StateStore(config.state_file)

    def deploy(
        self,
        cert_cfg: CertificateConfig,
        target: TargetAliyunClb,
        issue_domain: str,
        key_pem: str,
        fullchain_pem: str,
    ) -> str:
        assert_certificate_rsa(fullchain_pem)
        private_key = ensure_rsa_private_key_pkcs1(key_pem)

        probe_hosts = [target.probe_host or cert_cfg.issue_domains[0]]
        probe_hosts.extend(target.domain_extensions)
        for host in probe_hosts:
            if not cert_covers_domain(fullchain_pem, host):
                raise DeployError(f"certificate SAN does not cover CLB domain: {host}")

        cert_name = f"{cert_cfg.name}-{issue_domain}-{int(time.time())}"[:80]
        try:
            new_id = self.client.upload_server_certificate(
                region_id=target.region_id,
                server_certificate=fullchain_pem,
                private_key=private_key,
                server_certificate_name=cert_name,
            )
        except AliyunSlbError as exc:
            raise DeployError(f"UploadServerCertificate failed: {exc}") from exc

        logger.info("uploaded CLB cert ServerCertificateId=%s", new_id)

        failures: list[tuple[str, str]] = []
        successes: list[str] = []

        # 默认监听
        listener_key = clb_state_key(target)
        try:
            self.client.set_https_listener_certificate(
                region_id=target.region_id,
                load_balancer_id=target.load_balancer_id,
                listener_port=target.listener_port,
                server_certificate_id=new_id,
            )
            primary = target.probe_host or cert_cfg.issue_domains[0]
            ok, msg = self._probe_with_retry(primary)
            if not ok:
                raise DeployError(f"probe failed for {primary}: {msg}")
            self.state.update_after_deploy(
                listener_key,
                new_id,
                cleanup_days=self.config.old_cert_cleanup_days,
            )
            successes.append(listener_key)
        except (DeployError, AliyunSlbError) as exc:
            failures.append((listener_key, str(exc)))
            logger.error("CLB listener deploy failed: %s", exc)

        # SNI 扩展域
        if target.domain_extensions:
            try:
                extensions = self.client.describe_domain_extensions(
                    region_id=target.region_id,
                    load_balancer_id=target.load_balancer_id,
                    listener_port=target.listener_port,
                )
            except AliyunSlbError as exc:
                for domain in target.domain_extensions:
                    failures.append((domain, f"DescribeDomainExtensions failed: {exc}"))
                extensions = []

            by_domain = {str(item.get("Domain", "")).lower(): item for item in extensions}
            for domain in target.domain_extensions:
                ext_key = clb_state_key(target, domain)
                item = by_domain.get(domain.lower())
                if not item or not item.get("DomainExtensionId"):
                    failures.append((domain, "domain extension not found on listener"))
                    continue
                try:
                    self.client.set_domain_extension_certificate(
                        region_id=target.region_id,
                        domain_extension_id=str(item["DomainExtensionId"]),
                        server_certificate_id=new_id,
                    )
                    ok, msg = self._probe_with_retry(domain)
                    if not ok:
                        raise DeployError(f"probe failed for {domain}: {msg}")
                    self.state.update_after_deploy(
                        ext_key,
                        new_id,
                        cleanup_days=self.config.old_cert_cleanup_days,
                    )
                    successes.append(ext_key)
                except (DeployError, AliyunSlbError) as exc:
                    failures.append((domain, str(exc)))
                    logger.error("CLB extension deploy failed for %s: %s", domain, exc)

        if failures and not successes:
            raise DeployError(
                f"CLB deploy failed cert={new_id}: "
                + "; ".join(f"{k}: {r}" for k, r in failures)
            )
        if failures:
            raise DeployError(
                f"partial CLB deploy cert={new_id}; "
                f"ok={successes}; failed="
                + "; ".join(f"{k}: {r}" for k, r in failures)
            )
        return new_id

    def _probe_with_retry(self, domain: str) -> tuple[bool, str]:
        last_msg = "probe failed"
        for attempt in range(1, self.config.probe_retries + 1):
            ok, msg = tls_probe(
                domain,
                min_valid_days=self.config.min_valid_days,
                server_hostname=domain,
            )
            if ok:
                logger.info("CLB probe ok %s: %s (attempt %d)", domain, msg, attempt)
                return True, msg
            last_msg = msg
            logger.warning(
                "CLB probe failed %s: %s (attempt %d/%d)",
                domain,
                msg,
                attempt,
                self.config.probe_retries,
            )
            if attempt < self.config.probe_retries:
                time.sleep(self.config.probe_interval_sec)
        return False, last_msg

    def cleanup_old_certs(self) -> list[str]:
        deleted: list[str] = []
        states = self.state.load()

        for domain, cert_id in self.state.list_pending_cleanup():
            if not domain.startswith("clb:"):
                continue
            # 仍被其它 state 当作 current 则跳过（同 region 共用 ServerCertificateId）
            still_used = any(
                k != domain and st.current_cert_id == cert_id for k, st in states.items()
            )
            if still_used:
                logger.warning(
                    "skip delete CLB cert %s still referenced as current elsewhere",
                    cert_id,
                )
                continue

            # region from key: clb:{region}:{lb}:{port}[:domain]
            parts = domain.split(":")
            region_id = parts[1] if len(parts) >= 2 else ""
            if not region_id:
                continue
            try:
                self.client.delete_server_certificate(
                    region_id=region_id,
                    server_certificate_id=cert_id,
                )
                self.state.clear_previous(domain)
                deleted.append(cert_id)
                logger.info("deleted old CLB cert %s for %s", cert_id, domain)
            except AliyunSlbError as exc:
                logger.warning("skip delete CLB cert %s for %s: %s", cert_id, domain, exc)
        return deleted
