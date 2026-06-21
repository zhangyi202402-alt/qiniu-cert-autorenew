"""部署状态持久化：current/previous certID 与旧证清理时间。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class DomainState:
    """单个 CDN 域名的证书部署状态。"""

    current_cert_id: str = ""           # 当前绑定的 certID
    previous_cert_id: str = ""          # 上一次成功部署的 certID（待清理）
    previous_cleanup_after: str = ""    # 允许 DELETE previous 的 ISO 时间
    last_deploy_at: str = ""            # 最近一次成功部署时间
    last_probe_ok: bool = False         # 最近一次探活是否通过


class StateStore:
    """读写 state.json，默认路径见 config paths.state_file。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, DomainState]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            domain: DomainState(**values)
            for domain, values in raw.items()
        }

    def save(self, states: dict[str, DomainState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {domain: asdict(state) for domain, state in states.items()}
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def get(self, domain: str) -> DomainState:
        return self.load().get(domain, DomainState())

    def update_after_deploy(
        self,
        domain: str,
        new_cert_id: str,
        cleanup_days: int = 7,
    ) -> None:
        """
        单域名部署成功后更新状态。

        若此前已有 current_cert_id，将其记入 previous 并设置 cleanup_after，
        供 cleanup 在换绑满 N 天后删除旧证。
        """
        states = self.load()
        prev = states.get(domain, DomainState())
        cleanup_after = datetime.now(timezone.utc).replace(microsecond=0)
        from datetime import timedelta

        cleanup_iso = (cleanup_after + timedelta(days=cleanup_days)).isoformat()
        states[domain] = DomainState(
            current_cert_id=new_cert_id,
            previous_cert_id=prev.current_cert_id or prev.previous_cert_id,
            previous_cleanup_after=cleanup_iso if prev.current_cert_id else "",
            last_deploy_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            last_probe_ok=True,
        )
        self.save(states)

    def list_pending_cleanup(self) -> list[tuple[str, str]]:
        """返回已到清理时间、(域名, previous_cert_id) 列表。"""
        now = datetime.now(timezone.utc)
        result: list[tuple[str, str]] = []
        for domain, state in self.load().items():
            if not state.previous_cert_id or not state.previous_cleanup_after:
                continue
            try:
                due = datetime.fromisoformat(state.previous_cleanup_after)
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if now >= due:
                result.append((domain, state.previous_cert_id))
        return result

    def clear_previous(self, domain: str) -> None:
        """旧证 DELETE 成功后清除 previous 字段。"""
        states = self.load()
        if domain not in states:
            return
        state = states[domain]
        states[domain] = DomainState(
            current_cert_id=state.current_cert_id,
            previous_cert_id="",
            previous_cleanup_after="",
            last_deploy_at=state.last_deploy_at,
            last_probe_ok=state.last_probe_ok,
        )
        self.save(states)
