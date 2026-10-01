"""Pure schema validation and preference precedence for workspace config."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from isycode.agent_loop import AGENT_STEP_CHOICES, ANSWER_TOKEN_CHOICES
from isycode.user_defaults import CHAT_TOKEN_BUDGET_CHOICES, UserDefaultsStore

WORKSPACE_CONFIG_VERSION = 1
WORKSPACE_CONFIG_MAX_BYTES = 64 * 1024
WORKSPACE_PREFERENCE_KEYS = frozenset({
    "default_role", "agent_steps", "answer_tokens", "chat_token_budget",
})
_ROLE_KINDS = UserDefaultsStore.ROLE_KINDS


@dataclass(frozen=True)
class WorkspaceConfigResult:
    values: dict[str, Any]
    warnings: tuple[str, ...] = ()
    error: str = ""

    @property
    def valid(self) -> bool:
        return not self.error


def _invalid(reason: str) -> WorkspaceConfigResult:
    return WorkspaceConfigResult({}, error=reason)


def parse_workspace_config(payload: bytes) -> WorkspaceConfigResult:
    """Validate a bounded UTF-8 v1 config payload without performing I/O."""
    if not isinstance(payload, bytes):
        return _invalid("Workspace config must be read as bytes.")
    if len(payload) > WORKSPACE_CONFIG_MAX_BYTES:
        return _invalid("Workspace config exceeds the 64 KiB size limit.")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _invalid("Workspace config is not valid UTF-8 JSON.")
    if not isinstance(data, dict) or type(data.get("version")) is not int:
        return _invalid("Workspace config must be a versioned JSON object.")
    if data["version"] != WORKSPACE_CONFIG_VERSION:
        return _invalid("Workspace config schema version is unsupported.")

    warnings = tuple(
        f"Unknown workspace config field ignored: {key}"
        for key in sorted(set(data) - WORKSPACE_PREFERENCE_KEYS - {"version"})
    )
    values = {key: value for key, value in data.items() if key in WORKSPACE_PREFERENCE_KEYS}
    role = values.get("default_role", ...)
    if role is not ... and role is not None and (
            not isinstance(role, dict)
            or set(role) != {"kind", "name"}
            or not isinstance(role.get("kind"), str)
            or role.get("kind") not in _ROLE_KINDS
            or not isinstance(role.get("name"), str)
            or not 1 <= len(role["name"]) <= 120):
        return _invalid("Workspace config default_role is invalid.")
    steps = values.get("agent_steps", ...)
    if steps is not ... and (type(steps) is not int or steps not in AGENT_STEP_CHOICES):
        return _invalid("Workspace config agent_steps is invalid.")
    tokens = values.get("answer_tokens", ...)
    if tokens is not ... and (type(tokens) is not int or tokens not in ANSWER_TOKEN_CHOICES):
        return _invalid("Workspace config answer_tokens is invalid.")
    budget = values.get("chat_token_budget", ...)
    if budget is not ... and (type(budget) is not int or budget not in CHAT_TOKEN_BUDGET_CHOICES):
        return _invalid("Workspace config chat_token_budget is invalid.")
    return WorkspaceConfigResult(values, warnings)


def resolve_workspace_preferences(user_values: dict[str, Any],
                                  workspace: WorkspaceConfigResult | None,
                                  overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Overlay workspace preferences and request overrides onto user defaults."""
    effective = {key: value for key, value in user_values.items()
                 if key in WORKSPACE_PREFERENCE_KEYS}
    if workspace is not None and workspace.valid:
        effective.update({key: value for key, value in workspace.values.items()
                          if key in WORKSPACE_PREFERENCE_KEYS})
    if overrides:
        effective.update({key: value for key, value in overrides.items()
                          if key in WORKSPACE_PREFERENCE_KEYS})
    return effective


__all__ = [
    "WORKSPACE_CONFIG_MAX_BYTES", "WORKSPACE_CONFIG_VERSION", "WorkspaceConfigResult",
    "parse_workspace_config", "resolve_workspace_preferences",
]
