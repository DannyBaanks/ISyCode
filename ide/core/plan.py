"""Append-only plan artifacts owned by the host."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from .ide_state import project_state

from .resident.store import append_jsonl, read_jsonl, utc_now


class PlanStore:
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.root = project_state(self.project_root) / "plans"

    def create(self, goal: str, session: str = "") -> str:
        plan_id = uuid.uuid4().hex
        append_jsonl(self.root / f"{plan_id}.jsonl", [{
            "type": "plan", "id": plan_id, "goal": goal,
            "status": "draft", "session": session, "timestamp": utc_now(),
        }])
        return plan_id

    def append(self, plan_id: str, record_type: str, **fields) -> None:
        append_jsonl(self.root / f"{plan_id}.jsonl", [{
            "type": record_type, "plan_id": plan_id,
            "timestamp": utc_now(), **fields,
        }])

    def ids(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.jsonl")) if self.root.is_dir() else []

    def latest_id(self) -> str | None:
        ids = self.ids()
        return ids[-1] if ids else None

    def records(self, plan_id: str | None = None) -> list[dict]:
        plan_id = plan_id or self.latest_id()
        return read_jsonl(self.root / f"{plan_id}.jsonl") if plan_id else []

    def context(self) -> dict:
        plan_id = self.latest_id()
        records = self.records(plan_id)
        return {"plan_id": plan_id, "records": records[-30:]}
