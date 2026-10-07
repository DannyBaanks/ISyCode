"""A visible task list the agent keeps for multi-step work.

The list lives only in the TUI's memory and on screen. Updating it performs
no effect and grants nothing, so it is not a Workspace Authority action; it
only lets the user see what the agent plans to do next.
"""
from __future__ import annotations

from typing import Any

from rich.text import Text

TASK_TOOL_NAME = "update_tasks"
TASK_STATUSES = ("pending", "in_progress", "completed")
MAX_TASKS = 30
MAX_TITLE_CHARS = 200

TASK_TOOL = {"type": "function", "function": {
    "name": TASK_TOOL_NAME,
    "description": (
        "Show the user your plan for multi-step work as a task list, replacing the previous "
        "list. Use it for work with three or more steps: add the steps, keep exactly one "
        "in_progress while you work on it, and mark each completed as soon as it is done. It "
        "performs no action by itself."),
    "parameters": {"type": "object", "properties": {
        "tasks": {"type": "array", "maxItems": MAX_TASKS, "items": {
            "type": "object", "properties": {
                "title": {"type": "string", "description": "Short imperative step."},
                "status": {"type": "string", "enum": list(TASK_STATUSES)},
            }, "required": ["title", "status"], "additionalProperties": False}},
    }, "required": ["tasks"], "additionalProperties": False},
}}


def validate_tasks(arguments: Any) -> list[dict[str, str]]:
    """Return a clean task list or raise ValueError."""
    tasks = arguments.get("tasks") if isinstance(arguments, dict) else None
    if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
        raise ValueError(f"tasks must be a list of at most {MAX_TASKS} items")
    clean = []
    for item in tasks:
        if not isinstance(item, dict):
            raise ValueError("each task needs a title and a status")
        title, status = item.get("title"), item.get("status")
        if not isinstance(title, str) or not title.strip() or status not in TASK_STATUSES:
            raise ValueError("each task needs a non-empty title and a known status")
        # One line each, without control characters that could redraw the screen.
        title = "".join(ch for ch in " ".join(title.split()) if ch.isprintable())[:MAX_TITLE_CHARS]
        clean.append({"title": title, "status": status})
    return clean


def render_tasks(tasks: list[dict[str, str]], *, collapsed: bool = False) -> Text:
    done = sum(1 for task in tasks if task["status"] == "completed")
    if tasks and done == len(tasks):
        # Finished plans collapse to one line so they stop taking chat space.
        return Text(f"Tasks · {done}/{len(tasks)} done ✓", style="bold #4ade80")
    if collapsed:
        current = next((task["title"] for task in tasks if task["status"] == "in_progress"), "")
        text = Text(f"▸ Tasks · {done}/{len(tasks)} done", style="bold #bb8cff")
        if current:
            text.append(f" · now: {current[:80]}", style="#c0c0c4")
        text.append("   click or Ctrl+T to expand", style="#6c757d")
        return text
    text = Text(f"▾ Tasks · {done}/{len(tasks)} done", style="bold #bb8cff")
    text.append("   click or Ctrl+T to fold\n", style="#6c757d")
    from isycode.operation_style import operation_color
    for task in tasks:
        color = operation_color(task["title"]) or "#c0c0c4"
        if task["status"] == "completed":
            text.append("  ✔ ", style="#4ade80")
            text.append(task["title"] + "\n", style="strike " + color)
        elif task["status"] == "in_progress":
            text.append("  ▶ ", style="#fbbf24")
            text.append(task["title"] + "\n", style="bold " + color)
        else:
            text.append("  ○ ", style="#6c757d")
            text.append(task["title"] + "\n", style=color)
    text.rstrip()
    return text


__all__ = ["MAX_TASKS", "TASK_STATUSES", "TASK_TOOL", "TASK_TOOL_NAME", "render_tasks",
           "validate_tasks"]
