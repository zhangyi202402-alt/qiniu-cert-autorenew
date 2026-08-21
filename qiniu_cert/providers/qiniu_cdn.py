"""七牛 CDN 证书部署 provider。"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from qiniu_cert.cert_utils import DeployError, cert_covers_domain, probe_force_https, read_pem, tls_probe
from qiniu_cert.config import (
    AppConfig,
    CertificateConfig,
    TargetQiniuCdn,
    find_cert_by_issue_domain,
    iter_targets,
)
from qiniu_cert.qiniu_client import QiniuApiError, QiniuClient
from qiniu_cert.state import StateStore

logger = logging.getLogger(__name__)


def qiniu_domains_for(cert_cfg: CertificateConfig) -> list[str]:
    domains: list[str] = []
    for t in iter_targets(cert_cfg):
        if isinstance(t, TargetQiniuCdn):
            domains.extend(t.domains)
    if not domains:
        domains = list(cert_cfg.qiniu_cdn_domains)
    return domains


class QiniuCdnProvider:
    """将证书部署到七牛 CDN 域名。"""

    def __init__(self, config: AppConfig, state: StateStore | None = None) -> None:
        self.config = config
        self.client = QiniuClient(config.qiniu_ak, config.qiniu_sk)
        self.state = state or StateStore(config.state_file)

    def deploy(
        self,
        cert_cfg: CertificateConfig,
        issue_domain: str,
        key_pem: str,
        fullchain_pem: str,
    ) -> str:
        domains = qiniu_domains_for(cert_cfg)
        if not domains:
            raise DeployError(f"no qiniu_cdn domains for certificate: {cert_cfg.name}")

        for cdn_domain in domains:
            if not cert_covers_domain(fullchain_pem, cdn_domain):
                raise DeployError(f"certificate SAN does not cover CDN domain: {cdn_domain}")

        failures: list[tuple[str, str]] = []
        successes: list[str] = []

        cert_name = f"{cert_cfg.name}-{issue_domain}-{int(time.time())}"
        try:
            cert_id = self.client.upload_ssl_cert(
                name=cert_name,
                private_key=key_pem,
                certificate_chain=fullchain_pem,
                common_name=domains[0],
            )
        except QiniuApiError as exc:
            raise DeployError(f"upload sslcert failed: {exc}") from exc

        logger.info("uploaded cert certID=%s", cert_id)

        for cdn_domain in domains:
            try:
                self._deploy_one_domain(cdn_domain, cert_id, cert_cfg)
                successes.append(cdn_domain)
            except (DeployError, QiniuApiError) as exc:
                reason = str(exc)
                failures.append((cdn_domain, reason))
                logger.error("deploy failed for %s: %s", cdn_domain, reason)

        if failures:
            summary = self._format_deploy_summary(cert_id, successes, failures)
            logger.error("%s", summary)
            raise DeployError(summary)

        return cert_id

    def deploy_from_files(
        self,
        issue_domain: str,
        key_path: Path,
        fullchain_path: Path,
        cert_cfg: CertificateConfig | None = None,
    ) -> str:
        cert_cfg = cert_cfg or find_cert_by_issue_domain(self.config, issue_domain)
        if not cert_cfg:
            raise DeployError(f"no certificate config for issue domain: {issue_domain}")
        return self.deploy(
            cert_cfg,
            issue_domain,
            read_pem(key_path),
            read_pem(fullchain_path),
        )

    def _deploy_one_domain(
        self,
        cdn_domain: str,
        cert_id: str,
        cert_cfg: CertificateConfig,
    ) -> None:
        https = cert_cfg.https
        for t in iter_targets(cert_cfg):
            if isinstance(t, TargetQiniuCdn) and cdn_domain in t.domains:
                https = t.https
                break

        self.client.bind_https(
            domain=cdn_domain,
            cert_id=cert_id,
            force_https=https.force_https,
            http2_enable=https.http2_enable,
            tls_versions=https.tls_versions,
        )
        logger.info("bound cert to %s", cdn_domain)

        ok, probe_msg = self._probe_with_retry(cdn_domain, https.force_https)
        if not ok:
            raise DeployError(f"probe failed for {cdn_domain}: {probe_msg}")

        self.state.update_after_deploy(
            cdn_domain,
            cert_id,
            cleanup_days=self.config.old_cert_cleanup_days,
        )
        logger.info("deploy ok for %s certID=%s", cdn_domain, cert_id)

    def _format_deploy_summary(
        self,
        cert_id: str,
        successes: list[str],
        failures: list[tuple[str, str]],
    ) -> str:
        lines = [
            f"partial deploy certID={cert_id}",
            f"succeeded ({len(successes)}): {', '.join(successes) or 'none'}",
        ]
        for domain, reason in failures:
            lines.append(f"failed {domain}: {reason}")
        if successes and failures:
            lines.append(
                "note: successful domains keep the new cert; failed domains unchanged; no rollback attempted"
            )
        return "; ".join(lines)

    def _probe_with_retry(self, domain: str, check_force_https: bool) -> tuple[bool, str]:
        last_msg = "probe failed"
        for attempt in range(1, self.config.probe_retries + 1):
            ok, msg = tls_probe(domain, min_valid_days=self.config.min_valid_days)
            if not ok:
                last_msg = msg
                logger.warning(
                    "probe failed %s: %s (attempt %d/%d)",
                    domain,
                    msg,
                    attempt,
                    self.config.probe_retries,
                )
                if attempt < self.config.probe_retries:
                    time.sleep(self.config.probe_interval_sec)
                continue

            if check_force_https:
                fh_ok, fh_msg = probe_force_https(domain)
                if not fh_ok:
                    last_msg = f"forceHttps: {fh_msg}"
                    logger.warning(
                        "forceHttps probe failed %s: %s (attempt %d/%d)",
                        domain,
                        fh_msg,
                        attempt,
                        self.config.probe_retries,
                    )
                    if attempt < self.config.probe_retries:
                        time.sleep(self.config.probe_interval_sec)
                    continue

            logger.info("probe ok %s: %s (attempt %d)", domain, msg, attempt)
            return True, msg

        return False, last_msg

    def cleanup_old_certs(self) -> list[str]:
        deleted: list[str] = []
        for domain, cert_id in self.state.list_pending_cleanup():
            if domain.startswith("clb:"):
                continue
            try:
                self.client.delete_cert(cert_id)
                self.state.clear_previous(domain)
                deleted.append(cert_id)
                logger.info("deleted old cert %s for %s", cert_id, domain)
            except QiniuApiError as exc:
                body = exc.body if isinstance(exc.body, dict) else {}
                code = body.get("code")
                if code == 400401:
                    self.state.clear_previous(domain)
                    deleted.append(cert_id)
                    logger.info(
                        "old cert %s for %s already absent, cleared state",
                        cert_id,
                        domain,
                    )
                    continue
                logger.warning(
                    "skip delete cert %s for %s: %s",
                    cert_id,
                    domain,
                    exc.body,
                )
        return deleted
