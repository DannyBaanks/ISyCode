"""Polling fallback for the agent panel: cursor, backoff, visible age.

Polling is the fallback, not the preferred transport: the configured
interval and the effective backoff are always visible to the user, and a
reconnect rebuilds snapshot + deltas through the store cursor. Nothing
here authorizes effects; it only reads the event log.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from isycode.agent_events import AgentEventStore


@dataclass
class PollReport:
    polls: int = 0
    events: int = 0
    reconnects: int = 0
    last_poll_at: float = 0.0
    last_interval: float = 0.0
    pending: bool = False

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "polls": self.polls, "events": self.events,
            "reconnects": self.reconnects, "last_poll_at": self.last_poll_at,
            "last_interval": self.last_interval, "pending": self.pending,
        }


class PollingCursor:
    """Interval polling with idle backoff and explicit reconnect."""

    def __init__(self, store: AgentEventStore, *, interval_s: float = 2.0,
                 backoff_factor: float = 2.0, max_interval_s: float = 10.0,
                 clock=time.monotonic):
        if not 0.1 <= interval_s <= 60.0:
            raise ValueError("polling interval must be between 0.1s and 60s")
        if not 1.0 <= backoff_factor <= 4.0:
            raise ValueError("backoff factor must be between 1 and 4")
        if max_interval_s < interval_s:
            raise ValueError("max interval must be >= the base interval")
        self.store = store
        self.base_interval = interval_s
        self.factor = backoff_factor
        self.max_interval = max_interval_s
        self.clock = clock
        self.cursor: dict[str, int] = {}
        self.report = PollReport()
        self._current_interval = interval_s

    def poll_once(self) -> int:
        """One poll; returns the number of new events folded."""
        started = self.clock()
        result = self.store.read(self.cursor)
        self.cursor = result.cursor
        report = self.report
        report.polls += 1
        report.events += len(result.events)
        report.last_interval = self._current_interval
        if result.events:
            self._current_interval = self.base_interval
            report.pending = False
        else:
            self._current_interval = min(self.max_interval,
                                         self._current_interval * self.factor)
        report.last_poll_at = started
        return len(result.events)

    def effective_interval(self) -> float:
        return self._current_interval

    def reconnect(self) -> int:
        """After a lost connection: rebuild from the store snapshot + deltas."""
        self.report.reconnects += 1
        self._current_interval = self.base_interval
        return self.poll_once()

    def age_s(self, *, now: float | None = None) -> float:
        if not self.report.last_poll_at:
            return float("inf")
        return max(0.0, (now if now is not None else self.clock()) - self.report.last_poll_at)


__all__ = ["PollingCursor", "PollReport"]
