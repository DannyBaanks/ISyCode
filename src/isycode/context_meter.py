"""Conservative local context-size display helpers.

Character counts are exact for the material ISyCode currently holds. Token
counts are only a display estimate unless a provider supplies a real context
limit; they never participate in authority or request truncation decisions.
"""
from __future__ import annotations

import json
from typing import Any


def _message_chars(message: dict[str, Any]) -> int:
    count = len(str(message.get("content") or ""))
    calls = message.get("tool_calls")
    if calls:
        count += len(json.dumps(calls, ensure_ascii=False, sort_keys=True))
    return count


def context_snapshot(messages: list[dict[str, Any]], *,
                     provider_limit_tokens: int | None = None) -> dict[str, int | str | None]:
    characters = sum(_message_chars(message) for message in messages if isinstance(message, dict))
    estimated_tokens = (characters + 3) // 4
    limit = (provider_limit_tokens if type(provider_limit_tokens) is int
             and provider_limit_tokens > 0 else None)
    return {
        "characters": characters,
        "estimated_tokens": estimated_tokens,
        "provider_limit_tokens": limit,
        "status": "measured-limit" if limit is not None else "estimated",
    }


def compact_context_label(messages: list[dict[str, Any]]) -> str:
    snapshot = context_snapshot(messages)
    tokens = int(snapshot["estimated_tokens"] or 0)
    if tokens >= 1000:
        value = f"~{tokens / 1000:.1f}k"
    else:
        value = f"~{tokens}"
    return f"ctx {value} est"


__all__ = ["compact_context_label", "context_snapshot"]
