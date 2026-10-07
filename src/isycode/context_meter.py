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
                     provider_limit_tokens: int | None = None,
                     reported_tokens: int | None = None,
                     limit_source: str = "unknown") -> dict[str, int | str | None]:
    characters = sum(_message_chars(message) for message in messages if isinstance(message, dict))
    estimated_tokens = (characters + 3) // 4
    measured = type(reported_tokens) is int and reported_tokens >= 0
    used_tokens = reported_tokens if measured else estimated_tokens
    limit = (provider_limit_tokens if type(provider_limit_tokens) is int
             and provider_limit_tokens > 0 else None)
    percent = min(100, round(used_tokens * 100 / limit)) if limit is not None else None
    return {
        "characters": characters,
        "estimated_tokens": estimated_tokens,
        "used_tokens": used_tokens,
        "provider_limit_tokens": limit,
        "used_source": "provider-usage" if measured else "local-estimate",
        "limit_source": limit_source if limit is not None else "unknown",
        "percent": percent,
        "status": "measured" if measured and limit is not None else
                  "partial" if measured or limit is not None else "estimated",
    }


def _compact_tokens(tokens: int) -> str:
    return f"{tokens / 1000:.0f}k" if tokens >= 1000 else str(tokens)


def compact_context_label(messages: list[dict[str, Any]], *,
                          provider_limit_tokens: int | None = None,
                          reported_tokens: int | None = None) -> str:
    snapshot = context_snapshot(messages, provider_limit_tokens=provider_limit_tokens,
                                reported_tokens=reported_tokens)
    used = int(snapshot["used_tokens"] or 0)
    if snapshot["provider_limit_tokens"] is None:
        value = _compact_tokens(used)
        if snapshot["used_source"] == "local-estimate":
            value = "~" + value
        return f"ctx {value} est · window ?" if snapshot["used_source"] == "local-estimate" else f"ctx {value} · window ?"
    limit = int(snapshot["provider_limit_tokens"])
    mark = "~" if snapshot["used_source"] == "local-estimate" else ""
    return f"ctx {mark}{_compact_tokens(used)}/{_compact_tokens(limit)} {snapshot['percent']}%"


__all__ = ["compact_context_label", "context_snapshot"]
