"""Pure presentation of IsySentinel's live state for the side rail.

The rail shows three things and decides nothing:

- the workspace mode and the permissions IsySentinel would currently accept,
  read from the same effective policy and owner registry the runtime enforces
  (a saved grant without a Secure owner is never shown as active);
- the latest ALLOW/DENY decisions, as the action journal recorded them: the
  action id, the verdict, the failed check names and who approved. Prompts,
  parameters, targets and contents are never in a journal record, so they
  cannot appear here either;
- whether the hash-chained journal verified.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping

from rich.text import Text

from isycode.actions import ACTION_BY_ID
from isycode.authority_view import DEDICATED_CONTROLS, grant_state
from isycode.tui_theme import status_phrase, switch_row, switch_rows

RECENT_DECISIONS = 8


@dataclass
class SentinelFeed:
    """Session counts and the newest decisions, oldest first."""

    recent: deque = field(default_factory=lambda: deque(maxlen=RECENT_DECISIONS))
    allowed: int = 0
    denied: int = 0
    journal: str = ""            # "" until verified; then e.g. "PASS · 1234 records"

    def add(self, record: Mapping[str, Any], *, count: bool = True) -> None:
        entry = decision_entry(record)
        if entry is None:
            return
        self.recent.append(entry)
        if count:
            if entry["allowed"]:
                self.allowed += 1
            else:
                self.denied += 1


def decision_entry(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Keep only the journal fields the rail shows; ignore anything malformed."""
    if not isinstance(record, Mapping) or record.get("kind", "decision") != "decision":
        return None
    action = record.get("action")
    if not isinstance(action, str) or not action:
        return None
    failed = record.get("failed_checks")
    failed = [str(name)[:60] for name in failed[:3]] if isinstance(failed, list) else []
    stamp = record.get("time")
    return {
        "action": action[:80],
        "allowed": record.get("sentinel") == "ALLOW" and record.get("authority") is True,
        "failed": failed,
        "approval": record.get("approval") if record.get("approval") in {"user", "delegated"} else "",
        "time": stamp if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else None,
    }


def active_permissions(policy: Mapping[str, Any]) -> list[tuple[str, bool]]:
    """Settings labels with any grant Sentinel would accept now, and whether all are.

    One label can cover several actions (list, read and search share one). It
    is complete only when every saved grant under it is accepted, so an
    explicit denial of one of them never hides behind the others.
    """
    grants = policy.get("grants", {}) if isinstance(policy, Mapping) else {}
    states: dict[str, list[bool]] = {}
    for action, grant in sorted(grants.items()):
        state = grant_state(action, grant)
        if state == "blocked":
            continue
        spec = ACTION_BY_ID.get(action)
        label = DEDICATED_CONTROLS.get(action) or (spec.label if spec else action)
        states.setdefault(label, []).append(state == "on")
    return [(label, all(flags)) for label, flags in states.items() if any(flags)]


def render(feed: SentinelFeed, policy: Mapping[str, Any] | None, *,
           trusted: bool = False) -> tuple[Text, str]:
    """Rail body and folded title."""
    rows: list[Text] = []
    mode = (policy or {}).get("mode") if isinstance(policy, Mapping) else None
    if mode == "classic":
        mode_text = "Classic · trusted folder" if trusted else "Classic · asks before each change"
    elif mode == "security":
        mode_text = "Security · everything off until granted"
    else:
        mode_text = "Mode unknown · nothing is assumed granted"
    rows.append(Text(f"Mode · {mode_text}"))
    if policy is None:
        rows.append(switch_row(None, "Permissions", status_phrase("unavailable")))
    else:
        labels = active_permissions(policy)
        rows.append(Text(f"Active permissions · {len(labels)}"))
        rows += [switch_row(True, label, "" if complete else "partial · some actions denied")
                 for label, complete in labels] or [switch_row(False, "None", inactive=True)]
    rows.append(Text(""))
    if feed.recent:
        rows.append(Text("Latest decisions"))
        for entry in reversed(feed.recent):
            note = "allow" if entry["allowed"] else "deny"
            if entry["failed"]:
                note += " · " + ", ".join(entry["failed"])
            elif entry["approval"] == "user":
                note += " · you approved"
            elif entry["approval"] == "delegated":
                note += " · by your setting"
            if entry["time"] is not None:
                note += " · " + time.strftime("%H:%M:%S", time.localtime(entry["time"]))
            rows.append(switch_row(entry["allowed"], entry["action"], note))
    else:
        rows.append(Text("No decisions yet in this session"))
    if feed.journal:
        rows.append(Text(f"Journal · {feed.journal}"))
    title = f"IsySentinel · {feed.allowed} allow · {feed.denied} deny"
    return switch_rows(rows), title


__all__ = ["RECENT_DECISIONS", "SentinelFeed", "active_permissions", "decision_entry", "render"]
