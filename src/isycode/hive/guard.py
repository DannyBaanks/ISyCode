"""Hive write guard — refuses file writes outside the agent's own hive workspace.

Only guards the named Claude file tools. This lexical/physical path check
is an additional coordination constraint, not Workspace Authority, Sentinel
or protection against a hostile process racing filesystem changes.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .types import HiveWriteInput, HiveWriteDecision

GUARDED_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


def target_path(tool_input: dict[str, Any] | None, cwd: str | None) -> str | None:
    """Return the absolute path a tool call would write, or None if it names none."""
    if not tool_input or not isinstance(tool_input, dict):
        return None
    p = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(p, str):
        return None
    if os.path.isabs(p):
        return os.path.normpath(p)
    if cwd:
        return os.path.normpath(os.path.join(cwd, p))
    return None


def is_inside(parent: str, child: str, case_insensitive: bool) -> bool:
    """Check if child path is inside parent directory."""
    norm = (lambda p: p.lower()) if case_insensitive else (lambda p: p)
    parent_n = os.path.normpath(norm(parent))
    child_n = os.path.normpath(norm(child))
    try:
        rel = os.path.relpath(child_n, parent_n)
    except ValueError:
        return False
    return rel == "." or (not rel.startswith("..") and not os.path.isabs(rel))


def is_plumbing(rel: str, agent_id: str, is_god: bool) -> bool:
    """Files the hive protocol allows an agent to write."""
    own = f"agents/{agent_id}/"
    if rel == f"{own}memory.md":
        return True
    if rel.startswith(f"{own}outbox/") or rel.startswith(f"{own}inbox/"):
        return True
    if rel == "tasks.json":
        return True
    if is_god and (rel == "board.md" or rel.startswith("spawn-requests/")):
        return True
    return False


def hive_write_decision(i: HiveWriteInput) -> HiveWriteDecision:
    """Decide whether to deny a file write inside the hive."""
    if i["tool"] not in GUARDED_TOOLS:
        return {"deny": False, "reason": None}

    target = target_path(i["toolInput"], i.get("cwd"))
    if not target:
        return {"deny": False, "reason": None}

    norm = (lambda p: p.lower()) if i["caseInsensitive"] else (lambda p: p)
    hive_root_n = os.path.normpath(norm(i["hiveRoot"]))
    target_n = os.path.normpath(norm(target))

    lexical_inside = is_inside(hive_root_n, target_n, i["caseInsensitive"])
    physical_root = os.path.realpath(i["hiveRoot"])
    physical_target = os.path.realpath(target)
    physical_inside = is_inside(physical_root, physical_target, i["caseInsensitive"])
    if not lexical_inside and not physical_inside:
        return {"deny": False, "reason": None}
    if not lexical_inside or not physical_inside:
        return {"deny": True, "reason": "Hive coordination writes cannot traverse symbolic links."}

    reason = (
        "The hive folder is only for coordination: your own memory.md, inbox and outbox, "
        "and tasks.json"
        + (" (plus board.md and spawn-requests/ for you)" if i["isGod"] else "")
        + ". To reach another agent, write a message into your outbox. "
        "Save documents and other work in your working folder instead."
    )

    try:
        rel = os.path.relpath(target_n, hive_root_n).replace(os.sep, "/")
    except ValueError:
        return {"deny": False, "reason": None}

    if not is_plumbing(rel, i["agentId"], i["isGod"]):
        return {"deny": True, "reason": reason}

    try:
        physical_rel = os.path.normpath(norm(os.path.relpath(physical_target, physical_root))).replace(os.sep, "/")
    except ValueError:
        return {"deny": True, "reason": "Hive coordination writes cannot traverse symbolic links."}

    if not is_plumbing(physical_rel, i["agentId"], i["isGod"]) or physical_rel != norm(rel):
        return {"deny": True, "reason": "Hive coordination writes cannot traverse symbolic links."}

    return {"deny": False, "reason": None}