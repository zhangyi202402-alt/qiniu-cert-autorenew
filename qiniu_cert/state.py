"""部署状态持久化：current/previous certID 与旧证清理时间。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class DomainState:
    current_cert_id: str = ""
    previous_cert_id: str = ""
    previous_cleanup_after: str = ""
    last_deploy_at: str = ""


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, DomainState]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(DomainState)}
        return {
            domain: DomainState(**{k: v for k, v in values.items() if k in known})
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
        states = self.load()
        prev = states.get(domain, DomainState())
        cleanup_iso = (
            datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=cleanup_days)
        ).isoformat()
        states[domain] = DomainState(
            current_cert_id=new_cert_id,
            previous_cert_id=prev.current_cert_id or prev.previous_cert_id,
            previous_cleanup_after=cleanup_iso if prev.current_cert_id else "",
            last_deploy_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        self.save(states)

    def list_pending_cleanup(self) -> list[tuple[str, str]]:
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
        states = self.load()
        if domain not in states:
            return
        state = states[domain]
        states[domain] = DomainState(
            current_cert_id=state.current_cert_id,
            previous_cert_id="",
            previous_cleanup_after="",
            last_deploy_at=state.last_deploy_at,
        )
        self.save(states)
