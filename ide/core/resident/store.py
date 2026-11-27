"""Small JSONL persistence primitives used by the host-owned resident state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from core.ide_state import project_state, state_lock


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resident_root(project_root: Path) -> Path:
    return project_state(project_root) / "resident"


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            records.append({
                "type": "unknown",
                "status": "unknown",
                "source": str(path),
                "line": line_number,
                "reason": "malformed JSONL record",
            })
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            records.append({
                "type": "unknown",
                "status": "unknown",
                "source": str(path),
                "line": line_number,
                "reason": "JSONL record is not an object",
            })
    return records


def append_jsonl(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with state_lock(path.with_suffix(path.suffix + ".lock")):
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def latest_by_id(records: Iterable[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in records:
        record_id = record.get("id")
        if record_id:
            latest[str(record_id)] = record
    return latest
