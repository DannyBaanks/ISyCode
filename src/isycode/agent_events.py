"""Durable, bounded, sanitized event log for observable background agents.

Contract (version 1): every line in the JSONL log is one event with
event_id, sequence (monotonic per run_id), task_id, run_id, parent_run_id,
timestamp, type, state and a bounded public payload. The log is
observational: an event never authorizes tools, approvals or network.

Durability and quotas: payloads are redacted and byte-bounded, the file
rotates with one previous generation kept, a rotation writes a marker event
(never lose terminal states silently), and a corrupt line degrades the
store instead of crashing it. Reads are cursor-based so a reconnecting UI
gets snapshot + deltas with gap and duplicate detection.
"""
from __future__ import annotations

import json
import os
import secrets
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isycode.chat_sessions import ChatSessionStore
from isycode.workspace_setup import state_root

EVENT_CONTRACT_VERSION = 1
MAX_PAYLOAD_BYTES = 16 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_EVENTS_PER_RUN = 4096
EVENT_TYPES = frozenset({
    "start", "progress", "tool", "change", "test", "wait", "error", "finish",
    "log.rotated", "log.dropped", "queue",
})
EVENT_STATES = frozenset({
    "queued", "running", "waiting-input", "waiting-permission", "cancelling",
    "cancelled", "failed", "uncertain", "completed", "info",
})
# Terminal states, errors and queue acknowledgements are never dropped by the
# per-run quota; noisy progress may be, always with a marker event.
_PROTECTED_TYPES = frozenset({"start", "error", "finish", "queue", "log.rotated", "log.dropped"})
_PROTECTED_STATES = frozenset({
    "cancelled", "failed", "uncertain", "completed", "waiting-input", "waiting-permission",
})


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    sequence: int
    task_id: str
    run_id: str
    parent_run_id: str | None
    timestamp: float
    type: str
    state: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": EVENT_CONTRACT_VERSION,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "timestamp": self.timestamp,
            "type": self.type,
            "state": self.state,
            "payload": self.payload,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AgentEvent":
        return AgentEvent(
            event_id=data["event_id"], sequence=data["sequence"],
            task_id=data["task_id"], run_id=data["run_id"],
            parent_run_id=data.get("parent_run_id"),
            timestamp=data["timestamp"], type=data["type"], state=data["state"],
            payload=data.get("payload") or {},
        )


@dataclass
class ReadResult:
    events: list[AgentEvent]
    cursor: dict[str, int]
    gaps: list[dict[str, Any]] = field(default_factory=list)
    degraded: bool = False


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return ChatSessionStore._sanitize_text(value)
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _valid_id(value: str) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 64 and all(
        ch.isalnum() or ch in "-_" for ch in value)


class AgentEventStore:
    """One JSONL file per workspace, outside the checkout, mode 600."""

    def __init__(self, workspace_id: str, *, directory: Path | None = None):
        if not _valid_id(workspace_id):
            raise ValueError("workspace id is invalid")
        base = Path(directory) if directory is not None else state_root() / "agent-events"
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory = base
        self.path = base / f"{workspace_id}.jsonl"
        self.rotated_path = base / f"{workspace_id}.jsonl.1"
        self.sequences_path = base / f"{workspace_id}.sequences.json"
        self._sequences: dict[str, int] = self._load_sequences()
        self._run_counts: dict[str, int] = {}
        self.degraded = False

    def _load_sequences(self) -> dict[str, int]:
        try:
            data = json.loads(self.sequences_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): int(v) for k, v in data.items()
                        if _valid_id(str(k)) and isinstance(v, int) and v >= 1}
        except (OSError, ValueError):
            pass
        sequences: dict[str, int] = {}
        for path in (self.rotated_path, self.path):
            for event, _corrupt in self._scan(path):
                sequences[event.run_id] = max(sequences.get(event.run_id, 0), event.sequence) + 1
        return sequences

    def _save_sequences(self) -> None:
        payload = json.dumps(self._sequences, sort_keys=True).encode("utf-8")
        temporary = self.sequences_path.with_suffix(".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.sequences_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _scan(self, path: Path) -> list[tuple[AgentEvent, bool]]:
        if not path.exists():
            return []
        found: list[tuple[AgentEvent, bool]] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for raw in stream:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                        if data.get("version") != EVENT_CONTRACT_VERSION:
                            raise ValueError("unknown event version")
                        found.append((AgentEvent.from_dict(data), False))
                    except (ValueError, KeyError, TypeError):
                        found.append((None, True))
        except OSError:
            self.degraded = True
        return found

    def append(self, task_id: str, run_id: str, parent_run_id: str | None,
               event_type: str, state: str, payload: dict[str, Any] | None = None) -> AgentEvent:
        if not _valid_id(task_id) or not _valid_id(run_id):
            raise ValueError("task and run ids are invalid")
        if parent_run_id is not None and not _valid_id(parent_run_id):
            raise ValueError("parent run id is invalid")
        if event_type not in EVENT_TYPES:
            raise ValueError(f"event type must be one of {sorted(EVENT_TYPES)}")
        if state not in EVENT_STATES:
            raise ValueError(f"event state must be one of {sorted(EVENT_STATES)}")
        material = _redact(dict(payload or {}))
        encoded = json.dumps(material, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("event payload exceeds its limit")
        protected = event_type in _PROTECTED_TYPES or state in _PROTECTED_STATES
        count = self._run_counts.get(run_id)
        if count is None:
            count = sum(1 for path in (self.rotated_path, self.path)
                        for event, _ in self._scan(path) if event.run_id == run_id)
            self._run_counts[run_id] = count
        if count >= MAX_EVENTS_PER_RUN and not protected:
            dropped_key = f"_dropped_{run_id}"
            if dropped_key not in self._sequences:
                self._sequences[dropped_key] = 1
                self._write_line(self._build(task_id, run_id, parent_run_id,
                                             "log.dropped", "info",
                                             {"reason": "per-run event quota reached"}))
                self._save_sequences()
            raise ValueError("per-run event quota reached; noisy progress was dropped with a marker")
        estimated = len(encoded.encode("utf-8")) + 512
        if self.path.exists() and self.path.stat().st_size + estimated > MAX_FILE_BYTES:
            os.replace(self.path, self.rotated_path)
            self._write_line(self._build(
                task_id, run_id, parent_run_id, "log.rotated", "info",
                {"reason": "event log rotated; previous generation kept as .1"}))
        event = self._build(task_id, run_id, parent_run_id, event_type, state, material)
        self._write_line(event)
        self._run_counts[run_id] = count + 1
        self._save_sequences()
        return event

    def _build(self, task_id: str, run_id: str, parent_run_id: str | None,
               event_type: str, state: str, payload: dict[str, Any]) -> AgentEvent:
        sequence = self._sequences.get(run_id, 1)
        self._sequences[run_id] = sequence + 1
        return AgentEvent(
            event_id=secrets.token_hex(8), sequence=sequence, task_id=task_id,
            run_id=run_id, parent_run_id=parent_run_id, timestamp=time.time(),
            type=event_type, state=state, payload=payload,
        )

    def _write_line(self, event: AgentEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            descriptor = os.open(self.path, flags, 0o600)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                if os.name == "posix":
                    self.path.chmod(0o600)
        except OSError:
            self.degraded = True
            raise

    def read(self, cursor: dict[str, int] | None = None, *,
             limit: int = 500, run_ids: set[str] | None = None) -> ReadResult:
        """Events after the cursor per run, paged, with gaps and duplicates marked."""
        cursor = dict(cursor or {})
        seen_ids: set[str] = set()
        events: list[AgentEvent] = []
        gaps: list[dict[str, Any]] = []
        expected: dict[str, int] = {}
        for path in (self.rotated_path, self.path):
            for event, corrupt in self._scan(path):
                if corrupt:
                    gaps.append({"kind": "corrupt", "file": path.name})
                    continue
                if run_ids is not None and event.run_id not in run_ids:
                    continue
                if event.event_id in seen_ids:
                    gaps.append({"kind": "duplicate", "event_id": event.event_id})
                    continue
                seen_ids.add(event.event_id)
                if event.sequence <= cursor.get(event.run_id, 0):
                    continue
                wanted = expected.get(event.run_id)
                if wanted is not None and event.sequence > wanted:
                    gaps.append({"kind": "gap", "run_id": event.run_id,
                                 "from": wanted, "to": event.sequence - 1})
                expected[event.run_id] = event.sequence + 1
                events.append(event)
        events.sort(key=lambda event: (event.timestamp, event.run_id, event.sequence))
        page = events[:max(1, limit)]
        new_cursor = dict(cursor)
        for event in page:
            new_cursor[event.run_id] = max(new_cursor.get(event.run_id, 0), event.sequence)
        return ReadResult(events=page, cursor=new_cursor, gaps=gaps,
                          degraded=self.degraded or any(gap["kind"] == "corrupt" for gap in gaps))

    def snapshot(self, run_ids: set[str] | None = None) -> dict[str, AgentEvent]:
        """Latest event per run: the sidebar's starting point after a reconnect."""
        latest: dict[str, AgentEvent] = {}
        for path in (self.rotated_path, self.path):
            for event, corrupt in self._scan(path):
                if corrupt or (run_ids is not None and event.run_id not in run_ids):
                    continue
                current = latest.get(event.run_id)
                if current is None or (event.sequence, event.timestamp) >= (
                        current.sequence, current.timestamp):
                    latest[event.run_id] = event
        return latest


__all__ = ["AgentEvent", "AgentEventStore", "EVENT_CONTRACT_VERSION", "ReadResult"]
