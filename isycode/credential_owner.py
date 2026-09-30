"""Owned saving and revoking of provider API keys in the OS keyring.

The secret value never enters an ActionRequest, the decision journal or a
receipt: requests carry only the service, a label and a purpose, and the value
goes straight to the operating-system keyring through CredentialVault. Both
actions need a per-service Workspace Authority grant, a fresh one-use approval
and IsySentinel ALLOW. Keys are saved for the user, not for one workspace.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path
from typing import Any

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.credentials import CredentialVault, CredentialVaultError
from isycode.providers import PRESETS
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

GATEWAY_SERVICE = "isyco-gateway"
KEY_ID = re.compile(r"cred_[a-f0-9]{16}")


def credential_services() -> frozenset[str]:
    """Services a key may be saved for: the provider presets plus the ISyCo Gateway."""
    return frozenset(PRESETS) | {GATEWAY_SERVICE}


def _label(value: Any) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 96
            and value == " ".join(value.split())
            and all(char.isprintable() for char in value))


class CredentialOwner:
    """Save or revoke one API key after grant, approval and IsySentinel."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, *, vault: CredentialVault | None = None):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="credentials")
        # Raises CredentialVaultError when no secure OS keyring backend exists.
        self.vault = vault if vault is not None else CredentialVault()

    def add_request(self, service: str, name: str, purpose: str) -> ActionRequest:
        return ActionRequest("credentials.add", self.root, service, {
            "service": service, "name": name, "purpose": purpose,
        }, execution_owner="credentials")

    def add(self, request: ActionRequest, secret: str,
            approval: ActionApproval | None) -> ActionOutcome:
        params = request.parameters if isinstance(request, ActionRequest) else {}
        try:
            expected = self.add_request(params.get("service"), params.get("name"),
                                        params.get("purpose"))
        except (TypeError, ValueError):
            expected = None
        if expected is None or request != expected:
            return ActionOutcome("API key not saved.", "DENY", None, "request is malformed")
        if (not isinstance(secret, str) or not secret.strip() or "\n" in secret
                or "\r" in secret or len(secret) > 16_384):
            return ActionOutcome("API key not saved.", "DENY", None,
                                 "API key must be a non-empty single-line value")
        denied = self._authorize(request, approval)
        if denied is not None:
            return ActionOutcome("API key not saved.", "DENY", None, denied)
        try:
            key_id = self.vault.add(params["name"], params["service"], params["purpose"], secret)
        except (CredentialVaultError, OSError, ValueError) as exc:
            return ActionOutcome("API key not saved.", "ERROR", None,
                                 f"the OS keyring rejected the key ({type(exc).__name__})")
        receipt = self._receipt(request, f"added:{key_id}:{params['service']}")
        if receipt is None:
            return ActionOutcome("API key saved, but its receipt could not be journaled.",
                                 "NOT_VERIFIABLE", None, "durable action journal is unavailable")
        return ActionOutcome(f"API key saved for {params['service']}.", "ALLOW", receipt, key_id)

    def revoke_request(self, key_id: str) -> ActionRequest:
        if not isinstance(key_id, str) or not KEY_ID.fullmatch(key_id):
            raise ValueError("invalid key id")
        record = next((item for item in self.vault.list_metadata()
                       if item["id"] == key_id and not item["revoked"]), None)
        if record is None:
            raise ValueError("no active key with this id")
        return ActionRequest("credentials.revoke", self.root, record["service"], {
            "key_id": key_id, "service": record["service"],
        }, execution_owner="credentials")

    def revoke(self, request: ActionRequest, approval: ActionApproval | None) -> ActionOutcome:
        try:
            expected = self.revoke_request(request.parameters.get("key_id"))
        except (AttributeError, ValueError, CredentialVaultError, OSError):
            expected = None
        if expected is None or request != expected:
            return ActionOutcome("API key not removed.", "DENY", None,
                                 "the key changed or no longer exists")
        denied = self._authorize(request, approval)
        if denied is not None:
            return ActionOutcome("API key not removed.", "DENY", None, denied)
        try:
            removed = self.vault.revoke(request.parameters["key_id"])
        except (CredentialVaultError, OSError, ValueError) as exc:
            return ActionOutcome("API key not removed.", "ERROR", None,
                                 f"the OS keyring rejected the removal ({type(exc).__name__})")
        if not removed:
            return ActionOutcome("API key not removed.", "ERROR", None, "key was already removed")
        receipt = self._receipt(request, f"revoked:{request.parameters['key_id']}")
        if receipt is None:
            return ActionOutcome("API key removed, but its receipt could not be journaled.",
                                 "NOT_VERIFIABLE", None, "durable action journal is unavailable")
        return ActionOutcome("API key removed.", "ALLOW", receipt, "key revoked")

    def _authorize(self, request: ActionRequest, approval: ActionApproval | None) -> str | None:
        try:
            authority, decision = self.gate.authorize(
                request, approvals=self.approvals, approval=approval)
        except Exception:
            return "authorization evaluation failed"
        if authority.allowed and decision.allowed:
            return None
        if not authority.allowed:
            return authority.reason[:240]
        return "; ".join(check.reason for check in decision.checks if not check.passed)[:240]

    def _receipt(self, request: ActionRequest, result: str) -> ActionReceipt | None:
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", "SUCCESS",
                                hashlib.sha256(result.encode("utf-8")).hexdigest())
        return receipt if self.gate.persist_receipt(request, receipt) else None


__all__ = ["CredentialOwner", "GATEWAY_SERVICE", "credential_services"]
