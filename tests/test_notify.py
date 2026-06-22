from __future__ import annotations

from qiniu_cert.notify import resolve_notify


def test_resolve_notify_from_env(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
qiniu:
  access_key: ak
  secret_key: sk
notify:
  provider: dingtalk
  webhook: "${DINGTALK_WEBHOOK}"
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
    monkeypatch.setenv("DINGTALK_WEBHOOK", "https://example.com/hook")
    webhook, provider = resolve_notify(cfg)
    assert webhook == "https://example.com/hook"
    assert provider == "dingtalk"


def test_resolve_notify_prefers_env_over_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
qiniu:
  access_key: ak
  secret_key: sk
notify:
  provider: feishu
  webhook: "https://config.example.com/hook"
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
    monkeypatch.setenv("NOTIFY_WEBHOOK", "https://env.example.com/hook")
    webhook, provider = resolve_notify(cfg)
    assert webhook == "https://env.example.com/hook"
