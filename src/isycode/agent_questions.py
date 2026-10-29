"""One question from the agent to the person at the keyboard.

The answer is conversation, not authority. It cannot grant a tool, approve an
action, or change the workspace.
"""
from __future__ import annotations

from typing import Any


ASK_USER_TOOL_NAME = "ask_user"
MAX_QUESTION_CHARS = 500
MAX_CHOICES = 4
MAX_CHOICE_CHARS = 80
MAX_ANSWER_CHARS = 500

ASK_USER_TOOL = {"type": "function", "function": {
    "name": ASK_USER_TOOL_NAME,
    "description": (
        "Ask the person at the keyboard one question when you cannot continue "
        "without their choice. Use choices for a short selector, or omit them "
        "for a free-text answer. They can cancel. The answer grants no files, "
        "commands, approvals, or authority."
    ),
    "parameters": {"type": "object", "properties": {
        "question": {"type": "string", "description": "One plain question."},
        "choices": {"type": "array", "maxItems": MAX_CHOICES, "items": {
            "type": "string", "description": "One selectable answer.",
        }},
    }, "required": ["question"], "additionalProperties": False},
}}


def _plain(value: str, limit: int) -> str:
    cleaned = " ".join(value.replace("\x1b", "").split())
    return cleaned[:limit].strip()


def validate_question(arguments: Any) -> dict[str, Any]:
    """Return a bounded question, or raise ValueError."""
    if not isinstance(arguments, dict) or set(arguments) - {"question", "choices"}:
        raise ValueError("ask_user accepts only question and optional choices")
    question = arguments.get("question")
    if not isinstance(question, str):
        raise ValueError("ask_user requires one question")
    question = _plain(question, MAX_QUESTION_CHARS)
    if not question:
        raise ValueError("ask_user requires one question")
    raw_choices = arguments.get("choices")
    if raw_choices is None:
        return {"question": question, "choices": []}
    if not isinstance(raw_choices, list) or not 1 <= len(raw_choices) <= MAX_CHOICES:
        raise ValueError(f"choices must be 1 to {MAX_CHOICES} short answers")
    choices = []
    for item in raw_choices:
        if not isinstance(item, str):
            raise ValueError("each choice must be text")
        choice = _plain(item, MAX_CHOICE_CHARS)
        if not choice or choice in choices:
            raise ValueError("each choice must be a distinct short answer")
        choices.append(choice)
    return {"question": question, "choices": choices}
