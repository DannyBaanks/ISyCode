"""Small, transport-neutral event records for one agent turn.

The stream is observational only: records do not authorize tools, approvals or
network access.  TUI, headless and Mobile Host can serialize the same shapes
without sharing an executor.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


EVENT_VERSION = 1
MAX_EVENTS = 4096
MAX_EVENT_BYTES = 64 * 1024


@dataclass(frozen=True)
class TurnEvent:
    sequence: int
    type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": EVENT_VERSION,
            "sequence": self.sequence,
            "type": self.type,
            "payload": self.payload,
        }


class TurnEventStream:
    """Bounded in-memory event sequence for a single turn."""

    def __init__(self) -> None:
        self._events: list[TurnEvent] = []

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> TurnEvent:
        if (not isinstance(event_type, str) or not event_type
                or len(event_type) > 80 or not all(ch.isalnum() or ch in "._-" for ch in event_type)):
            raise ValueError("event type is invalid")
        if len(self._events) >= MAX_EVENTS:
            raise ValueError("turn event limit reached")
        material = {} if payload is None else payload
        if not isinstance(material, dict):
            raise ValueError("event payload must be an object")
        try:
            encoded = json.dumps(material, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("event payload must be JSON serializable") from exc
        if len(encoded.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError("event payload exceeds its limit")
        # Round-trip detaches caller-owned mutable objects.
        clean = json.loads(encoded)
        event = TurnEvent(len(self._events) + 1, event_type, clean)
        self._events.append(event)
        return event

    def records(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]

    def to_ndjson(self) -> str:
        return "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True)
                         for record in self.records())


__all__ = ["EVENT_VERSION", "TurnEvent", "TurnEventStream"]
