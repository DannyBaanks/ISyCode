"""Pure presentation of saved Workspace Authority grants for Settings.

Settings shows simple ON/OFF states, but the state must come from the same
registry the runtime enforces: a saved grant for an action without a Secure
execution owner is never presented as ON, and every saved grant is listed
somewhere so nothing live stays hidden. This module performs no effects and
grants nothing; it only reads the action and owner registries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from isycode.action_runtime import EXPLICIT_DENY_ACTIONS, OWNER_ACTIONS
from isycode.actions import ACTION_BY_ID, ACTION_CATALOG

OWNED_ACTIONS = frozenset().union(*OWNER_ACTIONS.values()) - EXPLICIT_DENY_ACTIONS

# Actions presented by a dedicated Settings control. The generic "other saved
# permissions" list covers every remaining saved grant.
DEDICATED_CONTROLS = {
    "workspace.files.list": "Read and search workspace files",
    "workspace.files.read": "Read and search workspace files",
    "workspace.files.search": "Read and search workspace files",
    "workspace.context.inject": "Read and search workspace files",
    "workspace.files.write": "Edit workspace files",
    "session.create": "Save conversations in this workspace",
    "session.resume": "Save conversations in this workspace",
    "provider.request": "Connect to the selected AI model",
    "gateway.files.read": "Check ISyCo Gateway",
    "mcp.discover": "Find Gateway tools",
    "gateway.semantic.read": "Search and understand code with Gateway",
    "mcp.invoke": "Run a Gateway tool",
    "lsp.start": "Local code help",
    "catalog.external.read": "Browse optional integrations",
    "mobile.host.start": "Mobile Host on this computer",
    "mobile.pair": "Mobile Host on this computer",
    "mobile.pair.issue": "Mobile Host on this computer",
}

MOBILE_HOST_ADDRESS = "127.0.0.1:8765"
MOBILE_PAIR_TARGET = "mobile-host"
# Target-scoped Mobile Host grants saved together with mobile.host.start.
MOBILE_PAIR_ACTIONS = ("mobile.pair", "mobile.pair.issue")


def grant_state(action_id: str, grant: Mapping[str, Any] | None) -> str:
    """Return "on", "off" or "blocked" as the runtime would treat the grant.

    "blocked" means no Secure execution owner exists, so a saved grant is
    ignored by IsySentinel's owner binding and must never render as ON.
    """
    if action_id not in OWNED_ACTIONS:
        return "blocked"
    return "on" if isinstance(grant, Mapping) and grant.get("enabled") is True else "off"


def displayed_on(action_id: str, grant: Mapping[str, Any] | None, scoped: bool = True) -> bool:
    """ON only when the action is owned, the grant is enabled and in scope."""
    return bool(scoped) and grant_state(action_id, grant) == "on"


def mobile_host_enabled(grants: Mapping[str, Any]) -> bool:
    start = grants.get("mobile.host.start", {})
    return (displayed_on("mobile.host.start", start,
                         MOBILE_HOST_ADDRESS in start.get("network_hosts", []))
            and all(displayed_on(action, grants.get(action, {}),
                                 MOBILE_PAIR_TARGET in grants.get(action, {}).get("targets", []))
                    for action in MOBILE_PAIR_ACTIONS))


def mobile_host_saved(grants: Mapping[str, Any]) -> bool:
    """Any saved Mobile Host grant, even partial, must stay visible and revocable."""
    return any(bool(grants.get(action, {}).get("enabled"))
               for action in ("mobile.host.start", *MOBILE_PAIR_ACTIONS))


@dataclass(frozen=True)
class SavedGrantRow:
    action_id: str
    label: str
    state: str
    scope: str
    approval_required: bool


def _scope_summary(grant: Mapping[str, Any]) -> str:
    parts = []
    for key, name in (("path_prefixes", "paths"), ("network_hosts", "hosts"),
                      ("executables", "programs"), ("targets", "targets")):
        values = grant.get(key, [])
        if values:
            parts.append(f"{name}: {len(values)}")
    return ", ".join(parts) or "no scope"


def other_saved_grants(grants: Mapping[str, Any]) -> list[SavedGrantRow]:
    """Every enabled saved grant without a dedicated control, in catalog order."""
    rows = []
    for action in ACTION_CATALOG:
        grant = grants.get(action.id)
        if (action.id in DEDICATED_CONTROLS or not isinstance(grant, Mapping)
                or grant.get("enabled") is not True):
            continue
        rows.append(SavedGrantRow(action.id, f"{action.group} · {action.label}",
                                  grant_state(action.id, grant), _scope_summary(grant),
                                  action.approval_required))
    return rows


__all__ = [
    "DEDICATED_CONTROLS", "MOBILE_HOST_ADDRESS", "MOBILE_PAIR_ACTIONS", "MOBILE_PAIR_TARGET",
    "OWNED_ACTIONS",
    "SavedGrantRow", "displayed_on", "grant_state", "mobile_host_enabled",
    "mobile_host_saved", "other_saved_grants",
]

if not set(DEDICATED_CONTROLS) <= set(ACTION_BY_ID):
    raise RuntimeError("Settings controls reference an unknown action.")
