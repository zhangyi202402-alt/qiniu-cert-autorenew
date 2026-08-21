from __future__ import annotations

from pathlib import Path

from qiniu_cert.acme_plan import (
    acme_cert_dir,
    acme_days_arg,
    build_issue_plans,
    dns_env_shell,
    domain_args_shell,
    primary_issue_domain,
)
from qiniu_cert.config import AcmeConfig, AppConfig, CertificateConfig, load_config


def test_primary_issue_domain_prefers_non_wildcard():
    assert primary_issue_domain(["*.example.com", "example.com"]) == "example.com"
    assert primary_issue_domain(["*.only.com"]) == "only.com"


def test_domain_args_shell_separate_d_flags():
    args = domain_args_shell(["a.com", "*.b.com"])
    assert args.startswith("-d ")
    assert "'-d a.com'" not in args
    assert "-d a.com" in args
    assert "-d '*.b.com'" in args


def test_acme_cert_dir_by_key_type():
    assert acme_cert_dir("example.com", "ec-256") == "example.com_ecc"
    assert acme_cert_dir("example.com", "rsa2048") == "example.com"


def test_acme_days_arg():
    cfg = AppConfig(
        qiniu_ak="ak",
        qiniu_sk="sk",
        certificates=[],
        state_file=Path("/tmp/state.json"),
        acme=AcmeConfig(renew_days=15),
    )
    assert acme_days_arg(cfg) == "-15"


def test_build_issue_plans_multiple_certs():
    config = AppConfig(
        qiniu_ak="ak",
        qiniu_sk="sk",
        certificates=[
            CertificateConfig(
                name="a",
                issue_domains=["a.com"],
                dns_provider="ali",
                qiniu_cdn_domains=["cdn.a.com"],
            ),
            CertificateConfig(
                name="b",
                issue_domains=["b.com", "*.b.com"],
                dns_provider="dns_tencent",
                qiniu_cdn_domains=["cdn.b.com"],
            ),
        ],
        state_file=Path("/tmp/state.json"),
        acme=AcmeConfig(key_type="ec-256"),
    )
    plans = build_issue_plans(config)
    assert len(plans) == 2
    assert plans[0].dns_hook == "dns_ali"
    assert plans[1].primary_domain == "b.com"
    assert plans[1].dns_hook == "dns_tencent"
    assert plans[1].cert_dir == "b.com_ecc"
    assert plans[0].deploy_hook == "qiniu_wrapper"
    assert "-d b.com" in plans[1].domain_args
    assert "*.b.com" in plans[1].domain_args


def test_build_issue_plans_clb_uses_rsa_and_clb_hook():
    from qiniu_cert.config import TargetAliyunClb

    config = AppConfig(
        qiniu_ak="",
        qiniu_sk="",
        aliyun_ak="ak",
        aliyun_sk="sk",
        certificates=[
            CertificateConfig(
                name="clb",
                issue_domains=["www.example.com"],
                dns_provider="dns_ali",
                key_type="rsa-2048",
                targets=[
                    TargetAliyunClb(
                        region_id="cn-hangzhou",
                        load_balancer_id="lb-1",
                        listener_port=443,
                    )
                ],
            )
        ],
        state_file=Path("/tmp/state.json"),
        acme=AcmeConfig(key_type="ec-256"),
    )
    plans = build_issue_plans(config)
    assert plans[0].key_type == "rsa-2048"
    assert plans[0].cert_dir == "www.example.com"
    assert plans[0].deploy_hook == "clb_wrapper"


def test_dns_env_shell_dedup(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
qiniu:
  access_key: ak
  secret_key: sk
certificates:
  - name: a
    issue_domains: [a.com]
    dns_provider: ali
    qiniu_cdn_domains: [cdn.a.com]
    dns_env:
      k: Ali_Key
      s: Ali_Secret
  - name: b
    issue_domains: [b.com]
    dns_provider: ali
    qiniu_cdn_domains: [cdn.b.com]
    dns_env:
      k: Ali_Key
      s: Ali_Secret
paths:
  state_file: .local/state/state.json
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("Ali_Key", "key1")
    monkeypatch.setenv("Ali_Secret", "sec1")
    out = dns_env_shell(str(cfg))
    assert out.count("export Ali_Key=") == 1
    assert "key1" in out


def test_load_config_acme_key_type(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
qiniu:
  access_key: ak
  secret_key: sk
acme:
  key_type: rsa2048
certificates:
  - name: t
    issue_domains: [example.com]
    dns_provider: dns_ali
    qiniu_cdn_domains: [cdn.example.com]
paths:
  state_file: .local/state/state.json
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.acme.key_type == "rsa2048"
    assert cfg.min_valid_days == 30
