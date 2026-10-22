"""Opt-in Bridge coordination: peers, messages, leases and wakes.

A Bridge lease is a traffic light between peers, never a grant. Every action in
this module still passes Workspace Authority, ISySentinel, a one-use approval
bound to the request digest, and the action journal. The identity token and any
lease token stay in this process memory: they never reach the transcript, a
receipt, the journal or an error message.

The Bridge is optional and opt-in. This module never starts a daemon and never
edits the Bridge workspace; it calls the documented handshake command.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.bridge import BridgeError, bridge_client, find_handshake
from isycode.security import ActionRequest

from isycode.bridge_contract import (
    BRIDGE_OWNER_ID, IDENTITY_PATTERN, MAX_TOPIC_CHARS, OPERATION_ACTIONS,
    OPERATIONS, operation_target,
)


def session_identity() -> str:
    """A per-process identity for this ISyCode instance.

    Two running TUIs get two identities, so they can address each other as
    peers instead of pretending to be the same agent.
    """
    return f"isycode_{os.getpid()}_{secrets.token_hex(2)}"


def _plain(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _safe_name(value: Any) -> bool:
    return isinstance(value, str) and IDENTITY_PATTERN.fullmatch(value) is not None


def _safe_text(value: Any, limit: int) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) > limit:
        return False
    return "\x00" not in value and not any(ord(char) < 32 for char in value)


class BridgeCoordinationOwner:
    """One Bridge coordination action after grant, sentinel and approval."""

    owner_id = BRIDGE_OWNER_ID
    actions = frozenset(OPERATION_ACTIONS.values())

    def __init__(self, root: Path, authority: Any, approvals: Any, *,
                 identity: str | None = None, owner_id: str | None = None):
        self.root = Path(root).resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.identity = identity or session_identity()
        self.owner_id = owner_id or self.owner_id
        self.gate = ProductActionGate(self.root, authority, owner_id=self.owner_id)
        self._client = None

    # ── request preparation ───────────────────────────────────────────

    def prepare(self, operation: str, **extra: Any) -> ActionRequest:
        """Build the request a human reviews before anything reaches the Bridge."""
        if operation not in OPERATIONS:
            raise ValueError(f"unknown Bridge operation: {operation}")
        script = find_handshake().resolve(strict=True)
        executable = str(Path(sys.executable).resolve(strict=True))
        parameters: dict[str, Any] = {
            "executable": executable,
            "handshake": str(script),
            "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "operation": operation,
        }
        parameters.update(extra)
        # The owner id is a literal on purpose: the authority coverage audit
        # reads the binding of every ActionRequest from source.
        return ActionRequest(
            OPERATION_ACTIONS[operation], self.root,
            operation_target(operation, parameters), parameters,
            execution_owner="bridge_coordination")

    def _rebuild(self, request: ActionRequest) -> ActionRequest:
        operation = _plain(request.parameters.get("operation"))
        extra = {key: value for key, value in request.parameters.items()
                 if key not in {"executable", "handshake", "sha256", "operation"}}
        return self.prepare(operation, **extra)

    # ── execution ─────────────────────────────────────────────────────

    def execute(self, request: ActionRequest, approval: Any = None) -> ActionOutcome:
        """Run one reviewed Bridge operation and journal its receipt."""
        operation = _plain(request.parameters.get("operation"))
        if operation not in OPERATIONS:
            return ActionOutcome("Bridge action denied.", "DENY", None,
                                 "unknown Bridge operation")
        try:
            rebuilt = self._rebuild(request)
        except (OSError, ValueError, BridgeError) as exc:
            return ActionOutcome("Bridge action denied.", "DENY", None,
                                 f"handshake unavailable: {type(exc).__name__}")
        if rebuilt != request:
            return ActionOutcome("Bridge action denied.", "DENY", None,
                                 "the Bridge request changed after review")
        _, decision = self.gate.authorize(request, approvals=self.approvals,
                                          approval=approval)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome("Bridge action denied.", "DENY", None,
                                 reason or "this action is not granted")
        try:
            text = self._perform(request)
        except BridgeError as exc:
            return ActionOutcome("Bridge action failed.", "ERROR", None, str(exc))
        except (OSError, ValueError) as exc:
            return ActionOutcome("Bridge action failed.", "ERROR", None,
                                 type(exc).__name__)
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, text):
            return ActionOutcome("Bridge receipt failed verification.",
                                 "NOT_VERIFYABLE", None, "digest mismatch")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Bridge receipt could not be persisted.",
                                 "NOT_VERIFYABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(text, "ALLOW", receipt,
                             "one approved Bridge coordination action completed")

    def _client_for(self):
        """One client per owner: the identity token stays in this process."""
        if self._client is None:
            self._client = bridge_client(self.identity, caps="isycode,tui")
        return self._client

    def _perform(self, request: ActionRequest) -> str:
        operation = _plain(request.parameters.get("operation"))
        parameters = request.parameters
        client = self._client_for()
        if operation == "connect":
            client.hello()
            return f"Bridge connected as {self.identity}."
        if operation == "peek":
            messages = client.peek()
            return "\n".join(_render_message(item) for item in messages) or "No messages."
        if operation == "send":
            client.send(_plain(parameters.get("to")),
                        _plain(parameters.get("kind")),
                        _plain(parameters.get("topic")),
                        _plain(parameters.get("payload")))
            return f"Message sent to {parameters.get('to')}."
        if operation == "wake":
            client.wake(_plain(parameters.get("to")),
                        _plain(parameters.get("message")))
            return f"Wake sent to {parameters.get('to')}."
        if operation == "lease.claim":
            client.claim(_plain(parameters.get("topic")),
                         int(parameters.get("ttl") or 300),
                         _plain(parameters.get("path")))
            return f"Lease claimed for {parameters.get('topic')}."
        if operation == "lease.release":
            client.release(_plain(parameters.get("topic")))
            return f"Lease released for {parameters.get('topic')}."
        raise BridgeError("unsupported Bridge operation")

    def disconnect(self) -> None:
        """Leave the peer registry. Tokens are dropped with the client."""
        if self._client is None:
            return
        try:
            self._client.goodbye()
        except BridgeError:
            pass
        self._client = None


def _render_message(item: dict[str, Any]) -> str:
    """One readable line per message. Unknown fields never reach the screen."""
    sender = _plain(item.get("from") or item.get("frm"))[:64]
    topic = _plain(item.get("topic"))[:MAX_TOPIC_CHARS]
    body = _plain(item.get("payload") or item.get("text"))[:400]
    kind = _plain(item.get("kind"))[:32]
    parts = [part for part in (sender, kind, topic) if part]
    return " · ".join(parts + ([body] if body else []))
