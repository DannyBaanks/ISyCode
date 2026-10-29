"""Sidebar model for observable background agents.

Rebuilds the parent/child run tree from the durable event store through a
cursor (snapshot first, then deltas; reconnect-safe). Every row carries
its run's own latest public state — runs are keyed by run_id at every
step, so concurrent siblings never mix. The model is presentation only:
it reads events and never authorizes, starts, or stops anything.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from isycode.agent_events import AgentEvent, AgentEventStore

FINAL_STATES = frozenset({"cancelled", "failed", "completed"})


@dataclass
class RunNode:
    run_id: str
    task_id: str
    parent_run_id: str | None
    state: str = "queued"
    last_type: str = ""
    last_activity: float = 0.0
    event_count: int = 0
    goal: str = ""
    children: list["RunNode"] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "task_id": self.task_id,
            "parent_run_id": self.parent_run_id, "state": self.state,
            "last_type": self.last_type, "last_activity": self.last_activity,
            "event_count": self.event_count, "goal": self.goal,
            "children": [child.run_id for child in self.children],
        }


class AgentPanelModel:
    """Cursor-driven fold of the event log into a stable run tree."""

    def __init__(self, store: AgentEventStore):
        self.store = store
        self.cursor: dict[str, int] = {}
        self.runs: dict[str, RunNode] = {}
        self.gaps: list[dict[str, Any]] = []
        self.refresh(limit=10_000)

    def refresh(self, *, limit: int = 500) -> int:
        result = self.store.read(self.cursor, limit=limit)
        self.gaps = result.gaps
        self.cursor = result.cursor
        for event in result.events:
            self._fold(event)
        return len(result.events)

    def _fold(self, event: AgentEvent) -> None:
        node = self.runs.get(event.run_id)
        if node is None:
            node = RunNode(run_id=event.run_id, task_id=event.task_id,
                           parent_run_id=event.parent_run_id)
            self.runs[event.run_id] = node
            if event.parent_run_id and event.parent_run_id in self.runs:
                parent = self.runs[event.parent_run_id]
                if node not in parent.children:
                    parent.children.append(node)
        elif event.parent_run_id and node.parent_run_id is None:
            node.parent_run_id = event.parent_run_id
            parent = self.runs.get(event.parent_run_id)
            if parent is not None and node not in parent.children:
                parent.children.append(node)
        if event.timestamp >= node.last_activity:
            node.state = event.state if event.type != "log.rotated" else node.state
            node.last_type = event.type
            node.last_activity = event.timestamp
        node.event_count += 1
        if event.type == "start" and isinstance(event.payload.get("goal"), str):
            node.goal = event.payload["goal"][:160]

    def tree(self) -> list[RunNode]:
        roots = [node for node in self.runs.values()
                 if not node.parent_run_id or node.parent_run_id not in self.runs]
        return sorted(roots, key=lambda node: node.last_activity, reverse=True)

    def detail(self, run_id: str, *, limit: int = 20) -> list[AgentEvent]:
        """Bounded recent public events for exactly one run."""
        events: list[AgentEvent] = []
        cursor: dict[str, int] = {}
        while len(events) < limit:
            result = self.store.read(cursor, limit=limit * 2, run_ids={run_id})
            batch = [event for event in result.events if event.run_id == run_id]
            events.extend(batch)
            if not batch or result.cursor == cursor:
                break
            cursor = result.cursor
        return events[-limit:]

    def counts_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for node in self.runs.values():
            counts[node.state] = counts.get(node.state, 0) + 1
        return counts

    def age_label(self, run_id: str, *, now: float | None = None) -> str:
        node = self.runs[run_id]
        delta = max(0.0, (now if now is not None else time.time()) - node.last_activity)
        if delta < 1:
            return "<1s"
        if delta < 60:
            return f"{int(delta)}s"
        if delta < 3600:
            return f"{int(delta // 60)}m"
        return f"{int(delta // 3600)}h"


__all__ = ["AgentPanelModel", "FINAL_STATES", "RunNode"]
