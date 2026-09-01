"""配置 targets 与向后兼容。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from qiniu_cert.config import (
    TargetAliyunCdn,
    effective_key_type,
    iter_targets,
    load_config,
)


def test_legacy_qiniu_cdn_domains_still_loads(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        textwrap.dedent(
            """
            qiniu: {access_key: "ak", secret_key: "sk"}
            acme: {email: "a@b.com", ca: letsencrypt, key_type: ec-256}
            certificates:
              - name: legacy
                issue_domains: [cdn.example.com]
                dns_provider: dns_ali
                qiniu_cdn_domains: [cdn.example.com]
            paths: {state_file: state.json}
            """
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    targets = list(iter_targets(cfg.certificates[0]))
    assert len(targets) == 1
    assert targets[0].type == "qiniu_cdn"
    assert targets[0].domains == ["cdn.example.com"]


def test_aliyun_clb_target_and_rsa_override(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        textwrap.dedent(
            """
            qiniu: {access_key: "", secret_key: ""}
            aliyun: {access_key: "aak", secret_key: "ask"}
            acme: {email: "a@b.com", ca: letsencrypt, key_type: ec-256}
            certificates:
              - name: clb1
                issue_domains: [www.example.com]
                key_type: rsa-2048
                dns_provider: dns_ali
                targets:
                  - type: aliyun_clb
                    region_id: cn-hangzhou
                    load_balancer_id: lb-xxx
                    listener_port: 443
                    domain_extensions: [api.example.com]
            paths: {state_file: state.json}
            """
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.aliyun_ak == "aak"
    assert cfg.aliyun_sk == "ask"
    t = list(iter_targets(cfg.certificates[0]))[0]
    assert t.type == "aliyun_clb"
    assert t.load_balancer_id == "lb-xxx"
    assert t.listener_port == 443
    assert t.domain_extensions == ["api.example.com"]
    assert effective_key_type(cfg.certificates[0], cfg.acme) == "rsa-2048"


def test_clb_with_ec_key_type_raises(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        textwrap.dedent(
            """
            qiniu: {access_key: "", secret_key: ""}
            aliyun: {access_key: "aak", secret_key: "ask"}
            acme: {email: "a@b.com", ca: letsencrypt, key_type: ec-256}
            certificates:
              - name: bad
                issue_domains: [www.example.com]
                dns_provider: dns_ali
                targets:
                  - type: aliyun_clb
                    region_id: cn-hangzhou
                    load_balancer_id: lb-xxx
                    listener_port: 443
            paths: {state_file: state.json}
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="rsa-2048"):
        load_config(p)


def test_aliyun_cdn_target_loads(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        textwrap.dedent(
            """
            qiniu: {access_key: "", secret_key: ""}
            aliyun: {access_key: "aak", secret_key: "ask"}
            acme: {email: "a@b.com", ca: letsencrypt, key_type: ec-256}
            certificates:
              - name: cdn1
                issue_domains: [cdn.example.com, static.example.com]
                dns_provider: dns_ali
                targets:
                  - type: aliyun_cdn
                    domains: [cdn.example.com, static.example.com]
                    https:
                      force_https: true
            paths: {state_file: state.json}
            """
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    t = list(iter_targets(cfg.certificates[0]))[0]
    assert isinstance(t, TargetAliyunCdn)
    assert t.type == "aliyun_cdn"
    assert t.domains == ["cdn.example.com", "static.example.com"]
    assert t.https.force_https is True
    assert effective_key_type(cfg.certificates[0], cfg.acme) == "ec-256"
