"""Visible, inert agent note for the current chat turn."""
from __future__ import annotations

from typing import Any

from isycode.tool_history import sanitize_historical_text


IDEA_BOX_TOOL_NAME = "update_idea_box"
IDEA_NUDGE_SECONDS = 150.0
IDEA_NUDGE_PREFIX = "Idea box check, not a user message."

IDEA_BOX_TOOL = {
    "type": "function",
    "function": {
        "name": IDEA_BOX_TOOL_NAME,
        "description": "Keep the small visible Idea box current with what is happening, what is done, and the next concrete step.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "A short status note, up to about 320 visible characters."},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
}


def validate_idea_box(arguments: Any) -> str:
    if not isinstance(arguments, dict) or set(arguments) != {"text"}:
        raise ValueError("update_idea_box requires exactly one text field")
    raw = arguments.get("text")
    if not isinstance(raw, str) or len(raw) > 2000:
        raise ValueError("idea box text must be a string no longer than 2000 characters")
    collapsed = " ".join(raw.split()).strip()
    if not collapsed:
        raise ValueError("idea box text cannot be empty")
    if not collapsed.isprintable():
        raise ValueError("idea box text must be printable")
    clean = sanitize_historical_text(collapsed)
    clean = " ".join(clean.split()).strip()
    if not clean:
        raise ValueError("idea box text cannot be empty")
    if len(clean) > 320:
        clean = clean[:317].rstrip() + "..."
    return clean


def idea_nudge(current: str) -> str:
    current = current or "empty"
    return (
        f"{IDEA_NUDGE_PREFIX} Call update_idea_box with what you are doing, what is done, "
        f"and the next concrete step. Current idea box: {current}. If you are repeating yourself, "
        "leaving the task, or stuck, stop and say what is blocked. This check adds no tools and no "
        "authority. Do not quote this check."
    )

