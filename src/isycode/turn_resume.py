"""Interrupted turn capture and resume state representation."""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any


@dataclass
class InterruptedTurn:
    """Snapshot of a conversation turn interrupted by transport or model error."""

    prompt: str
    messages: list[dict[str, Any]]
    partial_text: str = ""
    partial_reasoning: str = ""
    executed_tools: dict[str, str] = field(default_factory=dict)  # tool_call_id -> result content
    denied_tools: set[str] = field(default_factory=set)           # set of denied tool_call_ids
    created_at: float = field(default_factory=time.monotonic)
    error_reason: str = ""
