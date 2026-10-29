"""Measured output tokens per second.

A rate exists only when the provider reports a completion-token count and the
completion call has a positive duration. Received text is not turned into a
rate, and nothing here is a price.
"""
from __future__ import annotations

MAX_TOKENS = 10**12
MAX_ELAPSED_S = 24 * 60 * 60


def completion_tokens(usage: object) -> int | None:
    """Provider-reported output tokens, or None when the count is missing."""
    if not isinstance(usage, dict):
        return None
    if "completion_tokens" in usage:
        value = usage.get("completion_tokens")
    elif "output_tokens" in usage:
        value = usage.get("output_tokens")
    else:
        return None
    if type(value) is int and 0 <= value <= MAX_TOKENS:
        return value
    return None


def measure_rate(usage: object, elapsed_s: object) -> float | None:
    """Output tokens divided by the completion's wall clock.

    Returns None when either side was not actually measured.
    """
    tokens = completion_tokens(usage)
    if tokens is None or isinstance(elapsed_s, bool) or type(elapsed_s) not in {int, float}:
        return None
    if not 0 < float(elapsed_s) <= MAX_ELAPSED_S:
        return None
    return tokens / float(elapsed_s)


def format_rate(rate: float | None, *, measuring: bool = False) -> str:
    if measuring:
        return "measuring t/s"
    if rate is None:
        return "t/s —"
    if rate >= 100:
        return f"{rate:.0f} t/s"
    return f"{rate:.1f} t/s"


class ThroughputMeter:
    """Last measured turn. A failed turn does not invent or erase that rate."""

    def __init__(self) -> None:
        self.last_rate: float | None = None
        self.last_tokens: int | None = None
        self.last_elapsed_s: float | None = None
        self.measured_turns = 0
        self.measuring = False

    def note(self, usage: object, elapsed_s: object) -> float | None:
        rate = measure_rate(usage, elapsed_s)
        if rate is None:
            return None
        self.last_rate = rate
        self.last_tokens = completion_tokens(usage)
        self.last_elapsed_s = float(elapsed_s)
        self.measured_turns += 1
        return rate

    def rate_line(self, total_tokens: int, unknown: bool) -> str:
        mark = " +?" if unknown else ""
        tokens = f"{total_tokens / 1000:.0f}k" if total_tokens >= 10_000 else f"{total_tokens:,}"
        return f"{format_rate(self.last_rate, measuring=self.measuring)} · {tokens}{mark} tok"

    def widget_text(self, total_tokens: int, unknown: bool, context: str) -> str:
        mark = " +?" if unknown else ""
        return f"{format_rate(self.last_rate, measuring=self.measuring)}\n{total_tokens:,}{mark} tok\n{context}"
