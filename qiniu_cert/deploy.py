"""部署路由：按 certificate targets 分发到各云 provider。"""

from __future__ import annotations

import logging
from pathlib import Path

from qiniu_cert.cert_utils import DeployError, read_pem
from qiniu_cert.config import (
    AppConfig,
    CertificateConfig,
    TargetAliyunCdn,
    TargetAliyunClb,
    TargetQiniuCdn,
    find_cert_by_issue_domain,
    iter_targets,
)
from qiniu_cert.providers.qiniu_cdn import QiniuCdnProvider
from qiniu_cert.state import StateStore

logger = logging.getLogger(__name__)


class DeployService:
    """
    部署入口（兼容旧名 DeployService）。

    按 targets 调用 Qiniu CDN / Aliyun CLB；多 target 结果以分号拼接。
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state = StateStore(config.state_file)
        self._qiniu: QiniuCdnProvider | None = None
        self._clb = None
        self._aliyun_cdn = None

    @property
    def qiniu(self) -> QiniuCdnProvider:
        if self._qiniu is None:
            self._qiniu = QiniuCdnProvider(self.config, state=self.state)
        return self._qiniu

    @property
    def client(self):
        """兼容旧测试：暴露七牛 client。"""
        return self.qiniu.client

    def deploy_from_files(
        self,
        issue_domain: str,
        key_path: Path,
        fullchain_path: Path,
        cert_cfg: CertificateConfig | None = None,
        *,
        skip_probe: bool = False,
    ) -> str:
        cert_cfg = cert_cfg or find_cert_by_issue_domain(self.config, issue_domain)
        if not cert_cfg:
            raise DeployError(f"no certificate config for issue domain: {issue_domain}")
        if not cert_cfg.enabled:
            raise DeployError(
                f"certificate {cert_cfg.name!r} is disabled; skip deploy"
            )

        key_pem = read_pem(key_path)
        fullchain_pem = read_pem(fullchain_path)
        targets = list(iter_targets(cert_cfg))
        if not targets:
            raise DeployError(f"no deploy targets for certificate: {cert_cfg.name}")

        parts: list[str] = []
        failures: list[str] = []

        for target in targets:
            try:
                if isinstance(target, TargetQiniuCdn):
                    narrowed = CertificateConfig(
                        name=cert_cfg.name,
                        issue_domains=cert_cfg.issue_domains,
                        dns_provider=cert_cfg.dns_provider,
                        qiniu_cdn_domains=list(target.domains),
                        https=target.https,
                        dns_env=cert_cfg.dns_env,
                        key_type=cert_cfg.key_type,
                        targets=[target],
                    )
                    cert_id = self.qiniu.deploy(narrowed, issue_domain, key_pem, fullchain_pem)
                    parts.append(f"qiniu:{cert_id}" if len(targets) > 1 else cert_id)
                elif isinstance(target, TargetAliyunClb):
                    clb = self._get_clb_provider()
                    cert_id = clb.deploy(
                        cert_cfg,
                        target,
                        issue_domain,
                        key_pem,
                        fullchain_pem,
                        skip_probe=skip_probe,
                    )
                    parts.append(f"clb:{cert_id}" if len(targets) > 1 else cert_id)
                elif isinstance(target, TargetAliyunCdn):
                    alicdn = self._get_aliyun_cdn_provider()
                    cert_id = alicdn.deploy(
                        cert_cfg,
                        target,
                        issue_domain,
                        key_pem,
                        fullchain_pem,
                        skip_probe=skip_probe,
                    )
                    parts.append(f"aliyun_cdn:{cert_id}" if len(targets) > 1 else cert_id)
                else:
                    failures.append(f"unknown target type: {getattr(target, 'type', target)}")
            except DeployError as exc:
                failures.append(str(exc))
                logger.error("target deploy failed: %s", exc)

        if failures and not parts:
            raise DeployError("; ".join(failures))
        if failures:
            raise DeployError(
                f"partial deploy: ok=[{'; '.join(parts)}]; failed=[{'; '.join(failures)}]"
            )
        return "; ".join(parts) if len(parts) > 1 else parts[0]

    def _get_clb_provider(self):
        if self._clb is None:
            from qiniu_cert.providers.aliyun_clb import AliyunClbProvider

            self._clb = AliyunClbProvider(self.config, state=self.state)
        return self._clb

    def _get_aliyun_cdn_provider(self):
        if not hasattr(self, "_aliyun_cdn") or self._aliyun_cdn is None:
            from qiniu_cert.providers.aliyun_cdn import AliyunCdnProvider

            self._aliyun_cdn = AliyunCdnProvider(self.config, state=self.state)
        return self._aliyun_cdn

    def cleanup_old_certs(self) -> list[str]:
        deleted: list[str] = []
        states = self.state.load()
        if any(not k.startswith(("clb:", "aliyun_cdn:")) for k in states):
            deleted.extend(self.qiniu.cleanup_old_certs())
        if any(k.startswith("clb:") for k in states):
            clb = self._get_clb_provider()
            deleted.extend(clb.cleanup_old_certs())
        if any(k.startswith("aliyun_cdn:") for k in states):
            alicdn = self._get_aliyun_cdn_provider()
            deleted.extend(alicdn.cleanup_old_certs())
        return deleted
