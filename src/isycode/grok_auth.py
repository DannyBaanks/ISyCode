"""Approved official grok CLI sign-in, gated like every other execution owner.

The access token stays in ``~/.grok/auth.json`` and is never read here. The
owner launches ``grok login`` only after Workspace Authority, IsySentinel, a
fresh one-use approval and the durable action journal have all said yes, and
it records a receipt for the outcome instead of copying credential material.
"""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Any, Callable

from isycode import grok_session
from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


class GrokAuthOwner:
    """Own only the official grok CLI sign-in, with no token read or copy."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, *,
                 runner: Callable[..., Any] | None = None,
                 slot: str | None = None):
        from isycode.account_slots import active_slot, validate_slot_name
        self.root = Path(root).resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="grok_auth")
        self._runner = runner
        self.slot = validate_slot_name(slot) if slot is not None else active_slot("grok")

    def request(self, method: str, *, slot: str | None = None) -> ActionRequest:
        """Build the exact sign-in request the confirmation screen describes."""
        if method not in {"device", "browser"}:
            raise ValueError("unsupported grok login method")
        from isycode.account_slots import PRIMARY_SLOT, validate_slot_name
        target_slot = validate_slot_name(slot) if slot is not None else self.slot
        params: dict[str, Any] = {
            "executable": grok_session.grok_executable(),
            "operation": "login",
            "method": method,
        }
        if target_slot != PRIMARY_SLOT:
            params["slot"] = target_slot
        return ActionRequest("grok.login", self.root, "grok", params, execution_owner="grok_auth")

    def _receipt(self, request: ActionRequest, result: str) -> ActionReceipt | None:
        # A receipt is recorded only for a verified success (the journal accepts
        # FAILURE receipts only for the tailscale.* flows). It hashes a fixed
        # local result label; never persist raw CLI output, URLs, or tokens.
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", "SUCCESS",
                                hashlib.sha256(result.encode()).hexdigest())
        return receipt if self.gate.persist_receipt(request, receipt) else None

    async def begin(self, request: ActionRequest,
                    approval: ActionApproval | None, *,
                    on_line: Callable[[str], None] | None = None) -> ActionOutcome:
        """Authorize first, then run the exact official grok login process."""
        from isycode.account_slots import PRIMARY_SLOT, record_account_auth, validate_slot_name
        try:
            raw_slot = request.parameters.get("slot")
            target_slot = validate_slot_name(raw_slot) if raw_slot is not None else self.slot
            expected = self.request(request.parameters.get("method"), slot=target_slot)
        except (AttributeError, TypeError, ValueError):
            return ActionOutcome("Grok sign-in denied.", "DENY", None,
                                 "invalid sign-in request")
        if request != expected:
            return ActionOutcome("Grok sign-in denied.", "DENY", None,
                                 "sign-in identity changed")
        authority, decision = self.gate.authorize(request, approvals=self.approvals,
                                                  approval=approval)
        if not decision.allowed:
            if not authority.allowed:
                reason = authority.reason
            else:
                reason = next((check.reason for check in decision.checks
                               if not check.passed), "IsySentinel denied the sign-in")
            return ActionOutcome("Grok sign-in denied.", "DENY", None, reason)

        show = on_line if callable(on_line) else (lambda line: None)
        runner = self._runner if self._runner is not None else grok_session.run_login
        try:
            if target_slot == PRIMARY_SLOT:
                code = await runner(request.parameters["method"], show,
                                    request.parameters["executable"])
            else:
                code = await runner(request.parameters["method"], show,
                                    request.parameters["executable"], slot=target_slot)
        except (OSError, ValueError):
            code = None
        if code is None:
            return ActionOutcome("grok:launch-failed", "ERROR", None,
                                 "official grok login failed to launch")
        live_status = grok_session.status() if target_slot == PRIMARY_SLOT else grok_session.status(slot=target_slot)
        if code == 0 and live_status == "signed-in":
            record_account_auth("grok", target_slot, authenticated=True, plan="Grok sign-in")
            receipt = self._receipt(request, "grok:login-finished")
            if receipt is None:
                return ActionOutcome("Grok sign-in status is not verifiable.",
                                     "NOT_VERIFIABLE", None, "durable receipt unavailable")
            return ActionOutcome("grok:login-finished", "ALLOW", receipt,
                                 "official grok login completed")
        return ActionOutcome(f"grok:login-exited:{code}", "ERROR", None,
                             f"official grok login exited with status {code}")


__all__ = ["GrokAuthOwner"]
