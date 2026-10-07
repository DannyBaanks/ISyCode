"""Versioned effect taxonomy for one ISyCode policy.

This module classifies actions. It does not grant them, execute them, or
replace IsySentinel. Explicit denials stay in Workspace Authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from isycode.actions import ACTION_BY_ID, ActionSpec

POLICY_VERSION = 1

EFFECTS = frozenset({
    "read",
    "recoverable_mutation",
    "destruction",
    "privileged_metadata",
    "credential",
    "network",
    "publication",
})

# Closed translation of the registry's effect labels. An unknown label fails
# classification instead of becoming an implicit grant.
_FROM_REGISTRY = {
    "read": "read",
    "write": "recoverable_mutation",
    "destructive": "destruction",
    "sensitive": "privileged_metadata",
    "credential": "credential",
    "network": "network",
    "network-read": "network",
    "network-write": "network",
    "process": "recoverable_mutation",
    "external": "publication",
    "coordination": "privileged_metadata",
}

# Effects a Classic preset is allowed to mention. Publication and privileged
# metadata stay explicit even in Classic.
CLASSIC_PRESET_EFFECTS = frozenset({
    "read", "recoverable_mutation", "destruction", "credential", "network",
})


@dataclass(frozen=True)
class EffectStamp:
    """Binds one request digest to the policy version that classified it."""

    policy_version: int
    request_digest: str
    effect_class: str
    action_id: str


def effect_class(action_id: str) -> str:
    """Return the effect class or raise KeyError if the action is unclassified."""
    spec = ACTION_BY_ID.get(action_id)
    if not isinstance(spec, ActionSpec):
        raise KeyError(action_id)
    try:
        effect = _FROM_REGISTRY[spec.effect]
    except KeyError as exc:
        raise KeyError(action_id) from exc
    if effect not in EFFECTS:
        raise KeyError(action_id)
    return effect


def stamp(request) -> EffectStamp:
    """Classify an immutable request. The digest is the request's own digest."""
    from isycode.security import ActionRequest

    if not isinstance(request, ActionRequest):
        raise TypeError("effect stamp requires an ActionRequest")
    effect = effect_class(request.action_id)
    digest = request.digest
    if (not isinstance(digest, str) or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError("request digest is not bound")
    return EffectStamp(POLICY_VERSION, digest, effect, request.action_id)


def classic_preset_ids() -> frozenset[str]:
    """Action ids the Classic preset may cover. Security covers none."""
    from isycode.workspace_authority import CLASSIC_ACTIONS

    allowed = frozenset(CLASSIC_ACTIONS)
    for action_id in allowed:
        if effect_class(action_id) not in CLASSIC_PRESET_EFFECTS:
            raise RuntimeError(f"Classic preset includes a forbidden effect: {action_id}")
    return allowed


def implicit_actions(mode: str) -> frozenset[str]:
    """Actions a mode may supply without an explicit grant. Security is empty."""
    if mode == "security":
        return frozenset()
    if mode == "classic":
        return classic_preset_ids()
    raise ValueError("unknown workspace mode")
