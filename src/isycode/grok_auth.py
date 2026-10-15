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
                 runner: Callable[..., Any] | None = None):
        self.root = Path(root).resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="grok_auth")
        self._runner = runner

    def request(self, method: str) -> ActionRequest:
        """Build the exact sign-in request the confirmation screen describes."""
        if method not in {"device", "browser"}:
            raise ValueError("unsupported grok login method")
        return ActionRequest(
            "grok.login", self.root, "grok",
            {"executable": grok_session.grok_executable(),
             "operation": "login", "method": method},
            execution_owner="grok_auth")

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
        try:
            expected = self.request(request.parameters.get("method"))
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
            code = await runner(request.parameters["method"], show,
                                request.parameters["executable"])
        except (OSError, ValueError):
            code = None
        if code is None:
            return ActionOutcome("grok:launch-failed", "ERROR", None,
                                 "official grok login failed to launch")
        if code == 0 and grok_session.status() == "signed-in":
            receipt = self._receipt(request, "grok:login-finished")
            if receipt is None:
                return ActionOutcome("Grok sign-in status is not verifiable.",
                                     "NOT_VERIFIABLE", None, "durable receipt unavailable")
            return ActionOutcome("grok:login-finished", "ALLOW", receipt,
                                 "official grok login completed")
        return ActionOutcome(f"grok:login-exited:{code}", "ERROR", None,
                             f"official grok login exited with status {code}")


__all__ = ["GrokAuthOwner"]
