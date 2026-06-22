"""证书部署服务：上传 PEM、绑定 CDN 域名、探活、状态持久化。"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from qiniu_cert.cert_utils import DeployError, cert_covers_domain, probe_force_https, read_pem, tls_probe
from qiniu_cert.config import AppConfig, CertificateConfig, find_cert_by_issue_domain
from qiniu_cert.qiniu_client import QiniuApiError, QiniuClient
from qiniu_cert.state import StateStore

logger = logging.getLogger(__name__)


class DeployService:
    """将 acme.sh 签发的证书部署到七牛 CDN 域名。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.client = QiniuClient(config.qiniu_ak, config.qiniu_sk)
        self.state = StateStore(config.state_file)

    def deploy_from_files(
        self,
        issue_domain: str,
        key_path: Path,
        fullchain_path: Path,
        cert_cfg: CertificateConfig | None = None,
    ) -> str:
        """
        从本地 PEM 文件部署证书到配置中的全部 CDN 域名。

        acme.sh deploy hook 传入的 issue_domain 用于匹配 config.yaml 中的证书记录。
        多域名时按域名逐个部署：成功的保留新证并写 state，失败的仅记录错误，不回滚。
        """
        cert_cfg = cert_cfg or find_cert_by_issue_domain(self.config, issue_domain)
        if not cert_cfg:
            raise DeployError(f"no certificate config for issue domain: {issue_domain}")

        private_key = read_pem(key_path)
        fullchain = read_pem(fullchain_path)

        # 上传前校验 SAN，避免绑定到七牛后才发现证书不覆盖域名
        for cdn_domain in cert_cfg.qiniu_cdn_domains:
            if not cert_covers_domain(fullchain, cdn_domain):
                raise DeployError(f"certificate SAN does not cover CDN domain: {cdn_domain}")

        failures: list[tuple[str, str]] = []
        successes: list[str] = []

        # 一次上传，多个 CDN 域名共用同一 certID
        cert_name = f"{cert_cfg.name}-{issue_domain}-{int(time.time())}"
        try:
            cert_id = self.client.upload_ssl_cert(
                name=cert_name,
                private_key=private_key,
                certificate_chain=fullchain,
                common_name=cert_cfg.qiniu_cdn_domains[0],
            )
        except QiniuApiError as exc:
            raise DeployError(f"upload sslcert failed: {exc}") from exc

        logger.info("uploaded cert certID=%s", cert_id)

        for cdn_domain in cert_cfg.qiniu_cdn_domains:
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

    def _deploy_one_domain(
        self,
        cdn_domain: str,
        cert_id: str,
        cert_cfg: CertificateConfig,
    ) -> None:
        """单域名：绑定 HTTPS → 探活 → 成功后更新 state。"""
        self.client.bind_https(
            domain=cdn_domain,
            cert_id=cert_id,
            force_https=cert_cfg.https.force_https,
            http2_enable=cert_cfg.https.http2_enable,
            tls_versions=cert_cfg.https.tls_versions,
        )
        logger.info("bound cert to %s", cdn_domain)

        ok, probe_msg = self._probe_with_retry(cdn_domain, cert_cfg.https.force_https)
        if not ok:
            raise DeployError(f"probe failed for {cdn_domain}: {probe_msg}")

        # 仅探活通过后才写 state，避免失败场景下 state 与七牛实际不一致
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
        """汇总部分成功/失败信息，供日志与 DeployError 使用。"""
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
        """
        TLS 探活，默认最多重试 15 次、间隔 60 秒（约 15 分钟 CDN 生效窗口）。

        依次检查：证书链可达、剩余有效期、可选的 forceHttps 跳转。
        """
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
        """
        删除已到清理时间的旧 certID。

        七牛要求证书未绑定任何域名才能 DELETE；换绑后需等待 old_cert_cleanup_days 天。
        """
        deleted: list[str] = []
        for domain, cert_id in self.state.list_pending_cleanup():
            try:
                self.client.delete_cert(cert_id)
                self.state.clear_previous(domain)
                deleted.append(cert_id)
                logger.info("deleted old cert %s for %s", cert_id, domain)
            except QiniuApiError as exc:
                body = exc.body if isinstance(exc.body, dict) else {}
                code = body.get("code")
                # 400401：证书已不存在，视为已清理
                if code == 400401:
                    self.state.clear_previous(domain)
                    deleted.append(cert_id)
                    logger.info(
                        "old cert %s for %s already absent, cleared state",
                        cert_id,
                        domain,
                    )
                    continue
                # 400611 等：旧证仍被绑定，跳过等待下次 cron
                logger.warning(
                    "skip delete cert %s for %s: %s",
                    cert_id,
                    domain,
                    exc.body,
                )
        return deleted
