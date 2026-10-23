"""GUS, the ISyCode maintainer role (ADR 0011): a declared role, never authority.

The role document ``agents/gus.md`` names the actions GUS may ask for. Loading
it checks that list against the ceiling ADR 0011 approved and refuses a
document that asks for more, names an unknown action, or changes the role's
identity. A loaded role is guidance for the model and a filter on the tools it
is offered; every action still goes through Workspace Authority, IsySentinel,
its owner, the effect ledger and the journal, exactly as without the role.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from isycode.actions import ACTION_BY_ID
from isycode.workspace_trust import QUIET_FLOW_ACTIONS

ROLE_RESOURCE = "agents/gus.md"
MAX_ROLE_BYTES = 32 * 1024

# ADR 0011 D1: the recoverable local work Flow already runs quietly, plus Git
# review and commits. Push, credentials, provider and configuration, authority,
# mode, integrations, network and L1 tools are outside on purpose.
GUS_ACTION_CEILING = frozenset(QUIET_FLOW_ACTIONS | {"git.status", "git.diff", "git.commit"})

_FIELDS = ("id", "name", "mode", "actions")
_IDENTITY = {"id": "gus", "name": "GUS", "mode": "maintainer"}
_DOCUMENT = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n(.*)\Z", re.DOTALL)


class GusRoleError(ValueError):
    """The GUS role document is malformed or asks for more than ADR 0011 allows."""


@dataclass(frozen=True)
class GusRole:
    id: str
    name: str
    mode: str
    actions: frozenset[str]
    instructions: str


def _frontmatter(metadata: str) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    actions: list[str] = []
    in_actions = False
    for line in metadata.splitlines():
        if not line.strip():
            continue
        if in_actions and line.startswith("  - "):
            actions.append(line[4:].strip())
            continue
        in_actions = False
        key, separator, value = line.partition(":")
        if not separator or line[:1].isspace():
            raise GusRoleError(f"unexpected frontmatter line: {line.strip()[:80]!r}")
        key, value = key.strip(), value.strip()
        if key in fields:
            raise GusRoleError(f"duplicate frontmatter field: {key}")
        if key == "actions":
            if value:
                raise GusRoleError("actions must be a list, one '  - action.id' per line")
            in_actions = True
        fields[key] = value
    return fields, actions


def parse_role_document(text: str) -> GusRole:
    """Parse and verify one role document; raise GusRoleError instead of loosening it."""
    if len(text.encode("utf-8")) > MAX_ROLE_BYTES:
        raise GusRoleError("role document is larger than 32 KiB")
    match = _DOCUMENT.match(text)
    if match is None:
        raise GusRoleError("role document needs a '---' frontmatter block")
    fields, actions = _frontmatter(match.group(1))
    if set(fields) != set(_FIELDS):
        missing = sorted(set(_FIELDS) - set(fields))
        extra = sorted(set(fields) - set(_FIELDS))
        raise GusRoleError(f"frontmatter fields must be exactly {', '.join(_FIELDS)}"
                           f" (missing: {missing or '-'}, extra: {extra or '-'})")
    for key, expected in _IDENTITY.items():
        if fields[key] != expected:
            raise GusRoleError(f"{key} must be {expected!r}, not {fields[key]!r}")
    if not actions:
        raise GusRoleError("the role declares no actions")
    if len(set(actions)) != len(actions):
        raise GusRoleError("an action is declared twice")
    unknown = sorted(action for action in actions if action not in ACTION_BY_ID)
    if unknown:
        raise GusRoleError(f"unknown actions: {', '.join(unknown)}")
    beyond = sorted(set(actions) - GUS_ACTION_CEILING)
    if beyond:
        raise GusRoleError(f"actions beyond what ADR 0011 allows GUS: {', '.join(beyond)}")
    instructions = match.group(2).strip()
    if not instructions:
        raise GusRoleError("the role has no instructions")
    return GusRole(id=fields["id"], name=fields["name"], mode=fields["mode"],
                   actions=frozenset(actions), instructions=instructions)


def is_isycode_checkout(root: Path) -> bool:
    """D3: GUS is offered only in the ISyCode repository (two marker files, never read)."""
    try:
        return ((root / "src" / "isycode" / "gus_role.py").is_file()
                and (root / "src" / "isycode" / "agents" / "gus.md").is_file())
    except OSError:
        return False


def load_gus_role() -> GusRole:
    """The shipped GUS role, verified against ADR 0011."""
    try:
        text = resources.files("isycode").joinpath(ROLE_RESOURCE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GusRoleError(f"role document unavailable: {type(exc).__name__}") from exc
    return parse_role_document(text)


__all__ = ["GUS_ACTION_CEILING", "GusRole", "GusRoleError", "is_isycode_checkout",
           "load_gus_role", "parse_role_document"]
