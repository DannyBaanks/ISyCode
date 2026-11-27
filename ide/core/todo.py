"""Small append-only TODO store for the ISyCODE host UI."""

from __future__ import annotations

import uuid
from pathlib import Path
from .ide_state import project_state

from .resident.store import append_jsonl, latest_by_id, read_jsonl, utc_now


class TodoStore:
    def __init__(self, project_root: Path):
        self.path = project_state(project_root) / "todos.jsonl"

    def _records(self) -> dict[str, dict]:
        return latest_by_id(read_jsonl(self.path))

    def list(self) -> list[dict]:
        return sorted(self._records().values(), key=lambda item: item.get("created_at", ""))

    def add(self, text: str) -> dict:
        text = text.strip()
        if not text:
            raise ValueError("TODO text cannot be empty")
        item = {
            "type": "todo",
            "id": f"todo:{uuid.uuid4().hex}",
            "text": text,
            "status": "open",
            "created_at": utc_now(),
        }
        append_jsonl(self.path, [item])
        return item

    def toggle(self, item_id: str) -> dict:
        item = self._records().get(item_id)
        if not item:
            raise KeyError(item_id)
        updated = dict(item)
        updated["status"] = "done" if item.get("status") != "done" else "open"
        updated["updated_at"] = utc_now()
        append_jsonl(self.path, [updated])
        return updated

    def summary(self, limit: int = 3) -> str:
        items = self.list()
        open_items = [item for item in items if item.get("status") != "done"]
        if not open_items:
            return "TODO: clear"
        preview = " | ".join(item["text"] for item in open_items[:limit])
        remaining = len(open_items) - min(limit, len(open_items))
        return f"TODO: {preview}" + (f" +{remaining}" if remaining else "")
