"""Pure ISyCode action contracts and deny-by-default Systembility aggregation.

This module deliberately owns no policy files, approval prompts, receipts,
credential storage, or execution. Workspace Authority evaluates an immutable
request first; execution owners may proceed only after this Sentinel returns
ALLOW for the same request digest.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from isycode.actions import ACTION_BY_ID, ActionSpec


def _freeze(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        raise ValueError("Action parameters exceed the maximum nesting depth.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Action parameters must not contain non-finite numbers.")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if len(value) > 256 or not all(isinstance(key, str) for key in value):
            raise ValueError("Action parameter maps must have bounded string keys.")
        return MappingProxyType({key: _freeze(item, depth + 1)
                                 for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        if len(value) > 1024:
            raise ValueError("Action parameter lists exceed the size limit.")
        return tuple(_freeze(item, depth + 1) for item in value)
    raise ValueError("Action parameters must contain JSON-compatible values.")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class ActionRequest:
    """Immutable, bounded identity for one requested effect."""

    action_id: str
    workspace_root: Path
    target: str = ""
    parameters: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id or len(self.action_id) > 160:
            raise ValueError("Action request requires a bounded action identifier.")
        try:
            root = Path(self.workspace_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ValueError("Workspace root must resolve to a real directory.") from exc
        if not root.is_dir():
            raise ValueError("Workspace root must resolve to a real directory.")
        if not isinstance(self.target, str) or len(self.target) > 4096:
            raise ValueError("Action target must be a bounded string.")
        frozen = _freeze(self.parameters or {})
        encoded = json.dumps(_plain(frozen), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("Action parameters exceed the 64 KiB limit.")
        object.__setattr__(self, "workspace_root", root)
        object.__setattr__(self, "parameters", frozen)

    @property
    def digest(self) -> str:
        payload = {
            "action_id": self.action_id,
            "workspace_root": str(self.workspace_root),
            "target": self.target,
            "parameters": _plain(self.parameters),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthorityDecision:
    """Result from Workspace Authority, bound to one immutable request."""

    allowed: bool
    grant_id: str
    reason: str
    request_digest: str


@dataclass(frozen=True)
class SystembilityResult:
    name: str
    passed: bool
    reason: str


class Systembility(Protocol):
    name: str

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult: ...


@dataclass(frozen=True)
class DecisionCheck:
    name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class SentinelDecision:
    action_id: str
    request_digest: str
    checks: tuple[DecisionCheck, ...]

    @property
    def allowed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    @property
    def status(self) -> str:
        return "ALLOW" if self.allowed else "DENY"


class IsySentinel:
    """Pure check aggregator. Empty sets, malformed results, and exceptions deny."""

    def __init__(self, systembilities: Iterable[Systembility]):
        self._systembilities = tuple(systembilities)

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SentinelDecision:
        if not isinstance(request, ActionRequest):
            return SentinelDecision("invalid", "", (
                DecisionCheck("KnownAction", False, "invalid action request is denied"),
                DecisionCheck("Authority", False, "Workspace Authority result is unavailable"),
                DecisionCheck("SystembilitySet", bool(self._systembilities),
                              "checks configured; invalid request denied"),
            ))
        checks: list[DecisionCheck] = []
        spec: ActionSpec | None = ACTION_BY_ID.get(request.action_id)
        checks.append(DecisionCheck(
            "KnownAction", spec is not None,
            "action is registered" if spec else "unknown action is denied",
        ))
        authority_valid = (
            isinstance(authority, AuthorityDecision)
            and authority.allowed
            and bool(authority.grant_id)
            and authority.request_digest == request.digest
        )
        if not isinstance(authority, AuthorityDecision):
            authority_reason = "Workspace Authority result is unavailable"
        elif authority.request_digest != request.digest:
            authority_reason = "Workspace Authority result is bound to another request"
        else:
            authority_reason = authority.reason[:500] if authority.reason else "explicit grant required"
        checks.append(DecisionCheck("Authority", authority_valid, authority_reason))
        configured = bool(self._systembilities)
        checks.append(DecisionCheck(
            "SystembilitySet", configured,
            "applicable checks configured" if configured else "no Systembilities configured",
        ))

        # Evaluate every check even after a failure so the decision explains
        # the whole gate. Exceptions are reduced to a non-sensitive reason.
        for systembility in self._systembilities:
            name = str(getattr(systembility, "name", type(systembility).__name__))[:120]
            try:
                result = systembility.evaluate(request, authority)
                if (not isinstance(result, SystembilityResult)
                        or result.name != name or not isinstance(result.passed, bool)):
                    checks.append(DecisionCheck(name, False, "invalid Systembility result"))
                    continue
                checks.append(DecisionCheck(name, result.passed, str(result.reason)[:500]))
            except Exception:
                checks.append(DecisionCheck(name, False, "Systembility evaluation failed"))

        return SentinelDecision(request.action_id, request.digest, tuple(checks))


__all__ = [
    "ACTION_BY_ID", "ActionRequest", "AuthorityDecision", "DecisionCheck",
    "IsySentinel", "SentinelDecision", "Systembility", "SystembilityResult",
]
