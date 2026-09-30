"""Authority-bound, read-only inventory owner for the local Tailscale client."""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Any

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate, TailscaleAuthorityFacts
from isycode.approvals import ActionApprovalStore
from isycode.security import ActionRequest
from isycode.tailscale import DEFAULT_GATEWAY_PORT, TailscaleAdapter, TailscaleSnapshot
from isycode.workspace_authority import WorkspaceAuthority


class TailscaleReadOwner:
    """Inspect local status through the adapter and journal a bounded receipt."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, *, adapter: Any | None = None,
                 gateway_port: int = DEFAULT_GATEWAY_PORT):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.adapter = adapter or TailscaleAdapter(gateway_port=gateway_port)
        self.gateway_port = gateway_port

    def inspect(self) -> tuple[TailscaleSnapshot, ActionOutcome]:
        resolver = getattr(self.adapter, "resolve_executable", None)
        executable = resolver() if callable(resolver) else None
        if not isinstance(executable, str):
            snapshot = self.adapter.inspect()
            if not isinstance(snapshot, TailscaleSnapshot):
                snapshot = TailscaleSnapshot("unavailable")
            return snapshot, ActionOutcome("Tailscale inventory is unavailable.",
                                           "NOT_VERIFIABLE", None,
                                           "no CLI process was launched")
        gateway_url = f"http://127.0.0.1:{self.gateway_port}"
        request = ActionRequest(
            "tailscale.inspect", self.root, "tailscale",
            {"executable": executable, "gateway_url": gateway_url,
             "gateway_port": self.gateway_port}, execution_owner="tailscale_read")
        facts = TailscaleAuthorityFacts(
            cli_executable=executable, gateway_url=gateway_url,
            gateway_port=self.gateway_port)
        gate = ProductActionGate(self.root, self.authority, owner_id="tailscale_read",
                                 tailscale_facts=facts)
        _, decision = gate.authorize(request, approvals=self.approvals)
        if not decision.allowed:
            snapshot = TailscaleSnapshot("not_authorized", executable=executable,
                                         gateway_url=gateway_url)
            return snapshot, ActionOutcome(
                "Tailscale inventory is not authorized.", "DENY", None,
                "Workspace Authority, IsySentinel, or journal denied")
        snapshot = self.adapter.inspect()
        if (not isinstance(snapshot, TailscaleSnapshot)
                or snapshot.executable != executable):
            return TailscaleSnapshot("unavailable", executable=executable,
                                     gateway_url=gateway_url), ActionOutcome(
                "Tailscale inventory changed during inspection.", "NOT_VERIFIABLE", None,
                "executable identity changed")
        digest = hashlib.sha256(b"tailscale.inspect:bounded-local-inventory").hexdigest()
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", "SUCCESS", digest)
        if not gate.persist_receipt(request, receipt):
            return snapshot, ActionOutcome(
                "Tailscale inventory is not verifiable.", "NOT_VERIFIABLE", None,
                "durable receipt unavailable")
        return snapshot, ActionOutcome("Local Tailscale inventory inspected.",
                                       "ALLOW", receipt, "read-only bounded inventory")

    def authorized_snapshot(self) -> TailscaleSnapshot:
        """Inventory for another owner's preview, only after Authority and Sentinel allow it.

        Serve and login previews read the local CLI before their own mutation
        is authorized; that read is a `tailscale.inspect` effect and must be
        decided and journaled like any other.
        """
        snapshot, outcome = self.inspect()
        if outcome.decision != "ALLOW":
            raise ValueError("read-only Tailscale inventory is not authorized")
        return snapshot


__all__ = ["TailscaleReadOwner"]
