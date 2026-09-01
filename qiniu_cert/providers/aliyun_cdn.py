"""阿里云 CDN HTTPS 证书部署 provider。"""

from __future__ import annotations

import logging
import time

from qiniu_cert.cert_utils import DeployError, cert_covers_domain, probe_force_https, tls_probe
from qiniu_cert.clients.aliyun_cdn import AliyunCdnClient, AliyunCdnError
from qiniu_cert.config import AppConfig, CertificateConfig, TargetAliyunCdn
from qiniu_cert.state import StateStore

logger = logging.getLogger(__name__)


def aliyun_cdn_state_key(domain: str) -> str:
    return f"aliyun_cdn:{domain}"


def sanitize_cdn_cert_name(name: str, *, max_len: int = 63) -> str:
    cleaned = []
    for ch in name:
        if ch.isalnum() or ch in "._-":
            cleaned.append(ch)
        else:
            cleaned.append("-")
    out = "".join(cleaned).strip("-._")
    return (out or "cert")[:max_len]


class AliyunCdnProvider:
    """将证书部署到阿里云 CDN 加速域名。"""

    def __init__(self, config: AppConfig, state: StateStore | None = None) -> None:
        self.config = config
        if not config.aliyun_ak or not config.aliyun_sk:
            raise DeployError("aliyun access_key/secret_key required for CDN deploy")
        self.client = AliyunCdnClient(config.aliyun_ak, config.aliyun_sk)
        self.state = state or StateStore(config.state_file)

    def deploy(
        self,
        cert_cfg: CertificateConfig,
        target: TargetAliyunCdn,
        issue_domain: str,
        key_pem: str,
        fullchain_pem: str,
        *,
        skip_probe: bool = False,
    ) -> str:
        domains = list(target.domains)
        if not domains:
            raise DeployError(f"no aliyun_cdn domains for certificate: {cert_cfg.name}")

        for cdn_domain in domains:
            if not cert_covers_domain(fullchain_pem, cdn_domain):
                raise DeployError(f"certificate SAN does not cover CDN domain: {cdn_domain}")

        failures: list[tuple[str, str]] = []
        successes: list[str] = []
        last_cert_name = ""

        for cdn_domain in domains:
            cert_name = sanitize_cdn_cert_name(
                f"{cert_cfg.name}-{cdn_domain}-{int(time.time())}"
            )
            try:
                self.client.set_cdn_domain_ssl_certificate(
                    domain_name=cdn_domain,
                    cert_name=cert_name,
                    ssl_pub=fullchain_pem,
                    ssl_pri=key_pem,
                )
                if not skip_probe:
                    ok, probe_msg = self._probe_with_retry(
                        cdn_domain,
                        target.https.force_https,
                    )
                    if not ok:
                        raise DeployError(f"probe failed for {cdn_domain}: {probe_msg}")
                self.state.update_after_deploy(
                    aliyun_cdn_state_key(cdn_domain),
                    cert_name,
                    cleanup_days=self.config.old_cert_cleanup_days,
                )
                logger.info("deploy ok for %s certName=%s", cdn_domain, cert_name)
                successes.append(cdn_domain)
                last_cert_name = cert_name
            except (DeployError, AliyunCdnError) as exc:
                reason = str(exc)
                failures.append((cdn_domain, reason))
                logger.error("deploy failed for %s: %s", cdn_domain, reason)

        if failures:
            summary = self._format_deploy_summary(last_cert_name, successes, failures)
            logger.error("%s", summary)
            raise DeployError(summary)

        return last_cert_name

    def _format_deploy_summary(
        self,
        cert_name: str,
        successes: list[str],
        failures: list[tuple[str, str]],
    ) -> str:
        lines = [
            f"partial deploy certName={cert_name or 'n/a'}",
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
        """CDN upload 模式无独立 cert 删除 API；仅清理本地 state。"""
        cleared: list[str] = []
        for domain, cert_name in self.state.list_pending_cleanup():
            if not domain.startswith("aliyun_cdn:"):
                continue
            self.state.clear_previous(domain)
            cleared.append(cert_name)
            logger.info("cleared aliyun_cdn state for %s (certName=%s)", domain, cert_name)
        return cleared
