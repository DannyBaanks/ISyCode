"""Durable, provider-neutral instruction queue with public acks.

Three distinct intents: next_turn (does not touch active work), correct
(applied at the first supported safe boundary) and cancel (priority
interruption channel, not a message that waits). Every transition is
persisted before it is reported, so a crash between persist/ack/apply
replays idempotently: an applied instruction records its boundary and is
never applied twice; a received-but-not-applied one is re-driven on
restart. Instructions never carry authority: the destination re-evaluates
its own grants at application time, and a revocation while queued blocks
the effect. Messages to a closed run are rejected with a reason, never
silently migrated.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from isycode.chat_sessions import ChatSessionStore
from isycode.workspace_setup import state_root

INTENTS = frozenset({"next_turn", "correct", "cancel"})
ACK_STATES = frozenset({"queued", "received", "applied", "rejected"})
ACK_ORDER = {"queued": 0, "received": 1, "applied": 2, "rejected": 2}
MAX_CONTENT_CHARS = 4000
MAX_QUEUE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Instruction:
    message_id: str
    sequence: int
    task_id: str
    run_id: str
    sender: str
    intent: str
    content: str
    ack: str
    ack_reason: str
    boundary: str | None
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id, "sequence": self.sequence,
            "task_id": self.task_id, "run_id": self.run_id, "sender": self.sender,
            "intent": self.intent, "content": self.content, "ack": self.ack,
            "ack_reason": self.ack_reason, "boundary": self.boundary,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Instruction":
        return Instruction(
            message_id=data["message_id"], sequence=int(data["sequence"]),
            task_id=data["task_id"], run_id=data["run_id"], sender=data["sender"],
            intent=data["intent"], content=data["content"], ack=data["ack"],
            ack_reason=data.get("ack_reason", ""), boundary=data.get("boundary"),
            timestamp=float(data["timestamp"]),
        )

    def with_ack(self, ack: str, reason: str = "", boundary: str | None = None) -> "Instruction":
        return Instruction(self.message_id, self.sequence, self.task_id, self.run_id,
                           self.sender, self.intent, self.content, ack, reason,
                           boundary if boundary is not None else self.boundary,
                           time.time())


def _valid_id(value: str) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 64 and all(
        ch.isalnum() or ch in "-_" for ch in value)


class InstructionQueue:
    """Append-only transition log per workspace; last ack per message wins."""

    def __init__(self, workspace_id: str, *, directory: Path | None = None,
                 run_closed: Callable[[str], bool] | None = None):
        if not _valid_id(workspace_id):
            raise ValueError("workspace id is invalid")
        base = Path(directory) if directory is not None else state_root() / "instruction-queue"
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = base / f"{workspace_id}.jsonl"
        self._run_closed = run_closed or (lambda run_id: False)
        self._messages: dict[str, Instruction] = {}
        self._sequences: dict[str, int] = {}
        self._replay()

    def _replay(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            for raw in stream:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    item = Instruction.from_dict(json.loads(raw))
                except (ValueError, KeyError, TypeError):
                    continue
                current = self._messages.get(item.message_id)
                if current is None or ACK_ORDER[item.ack] >= ACK_ORDER[current.ack]:
                    self._messages[item.message_id] = item
                key = f"{item.task_id}/{item.run_id}"
                self._sequences[key] = max(self._sequences.get(key, 0), item.sequence)

    def _persist(self, instruction: Instruction) -> None:
        line = json.dumps(instruction.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        if self.path.exists() and self.path.stat().st_size + len(line) > MAX_QUEUE_BYTES:
            raise ValueError("instruction queue is full; drain or archive it first")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        descriptor = os.open(self.path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        self._messages[instruction.message_id] = instruction

    def submit(self, task_id: str, run_id: str, intent: str, content: str, *,
             sender: str = "user") -> Instruction:
        if not _valid_id(task_id) or not _valid_id(run_id) or not _valid_id(sender):
            raise ValueError("task, run and sender ids are invalid")
        if intent not in INTENTS:
            raise ValueError(f"intent must be one of {sorted(INTENTS)}")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("instruction content must be non-empty text")
        clean = ChatSessionStore._sanitize_text(content.strip())[:MAX_CONTENT_CHARS]
        if self._run_closed(run_id):
            raise ValueError(f"run {run_id} is closed; redirect explicitly instead")
        key = f"{task_id}/{run_id}"
        sequence = self._sequences.get(key, 0) + 1
        self._sequences[key] = sequence
        instruction = Instruction(
            message_id=secrets.token_hex(8), sequence=sequence, task_id=task_id,
            run_id=run_id, sender=sender, intent=intent, content=clean,
            ack="queued", ack_reason="", boundary=None, timestamp=time.time())
        self._persist(instruction)
        return instruction

    def get(self, message_id: str) -> Instruction | None:
        return self._messages.get(message_id)

    def pending(self, run_id: str | None = None) -> list[Instruction]:
        return [item for item in sorted(self._messages.values(),
                                        key=lambda item: (item.task_id, item.run_id, item.sequence))
                if item.ack in {"queued", "received"}
                and (run_id is None or item.run_id == run_id)]

    def mark_received(self, message_id: str) -> Instruction:
        current = self._require(message_id)
        if current.ack != "queued":
            return current
        updated = current.with_ack("received")
        self._persist(updated)
        return updated

    def apply(self, message_id: str, *, boundary: str,
              authority_check: Callable[[Instruction], tuple[bool, str]] | None = None
              ) -> Instruction:
        """Apply at a named safe boundary; idempotent and authority-re-checked."""
        current = self._require(message_id)
        if current.ack == "applied":
            return current
        if current.ack == "rejected":
            return current
        if not isinstance(boundary, str) or not boundary.strip():
            raise ValueError("an application boundary is required")
        if self._run_closed(current.run_id):
            updated = current.with_ack("rejected", "destination run is closed")
            self._persist(updated)
            return updated
        if authority_check is not None:
            allowed, reason = authority_check(current)
            if not allowed:
                updated = current.with_ack("rejected", reason or "authority denied at application")
                self._persist(updated)
                return updated
        updated = current.with_ack("applied", boundary=boundary.strip())
        self._persist(updated)
        return updated

    def reject(self, message_id: str, reason: str) -> Instruction:
        current = self._require(message_id)
        if current.ack in {"applied", "rejected"}:
            return current
        updated = current.with_ack("rejected", str(reason)[:200])
        self._persist(updated)
        return updated

    def _require(self, message_id: str) -> Instruction:
        current = self._messages.get(message_id)
        if current is None:
            raise KeyError(f"unknown instruction {message_id}")
        return current


__all__ = ["ACK_STATES", "INTENTS", "Instruction", "InstructionQueue"]
