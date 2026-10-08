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
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
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


_BAR_COLORS = ((60, "#77d8b0"), (85, "#e5c07b"), (101, "#e06c75"))


def _fit(text: str, width: int) -> str:
    if len(text) <= width:
        return text.rjust(width)
    return text[:max(0, width - 1)] + "…"


def usage_panel(messages: list[dict[str, Any]], width: int, rate_line: str, *,
                provider_limit_tokens: int | None = None,
                reported_tokens: int | None = None,
                limit_source: str = "unknown"):
    """Three right-aligned rows for the composer: context, a fill bar, rate and tokens.

    `~` before the used count marks a local estimate; `≈` before the window marks
    a window taken from the offline models.dev snapshot instead of the account.
    An unknown window draws an empty bar with `?` and is never divided by.
    """
    from rich.text import Text

    width = max(8, width)
    snap = context_snapshot(messages, provider_limit_tokens=provider_limit_tokens,
                            reported_tokens=reported_tokens, limit_source=limit_source)
    used = int(snap["used_tokens"] or 0)
    used_mark = "~" if snap["used_source"] == "local-estimate" else ""
    limit = snap["provider_limit_tokens"]
    percent = snap["percent"]
    if limit is None:
        head = f"ctx {used_mark}{_compact_tokens(used)} / ?"
    else:
        window_mark = "≈" if limit_source == "snapshot" else ""
        head = f"ctx {used_mark}{_compact_tokens(used)}/{window_mark}{_compact_tokens(int(limit))}"
    tail = " ?" if percent is None else f" {percent}%"
    cells = max(4, width - 2 - len(tail))
    filled = 0 if percent is None else min(cells, round(cells * int(percent) / 100))
    if percent is not None and percent > 0:
        filled = max(1, filled)
    color = next(c for bound, c in _BAR_COLORS if (percent or 0) < bound)

    panel = Text(_fit(head, width), style="#9aa3ad")
    panel.append("\n")
    bar = Text(" " * max(0, width - (cells + 2 + len(tail))))
    bar.append("[", style="#6b7280")
    bar.append("█" * filled, style=color)
    bar.append(("░" if percent is not None else "·") * (cells - filled), style="#3f4450")
    bar.append("]", style="#6b7280")
    bar.append(tail, style=color if percent is not None else "#6b7280")
    panel.append(bar)
    panel.append("\n")
    if len(rate_line) > width:  # keep the token count (and its +?) over the rate
        rate_line = rate_line.split(" · ")[-1]
    panel.append(_fit(rate_line, width), style="#9aa3ad")
    return panel


__all__ = ["compact_context_label", "context_snapshot", "usage_panel"]
