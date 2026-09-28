"""Short-lived, one-use human approval tokens bound to an ActionRequest."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from isycode.security import ActionRequest


@dataclass(frozen=True)
class ActionApproval:
    token: str = field(repr=False)
    request_digest: str
    expires_at: float


class ActionApprovalStore:
    """Process-local approval vault; it never grants a persistent action."""

    def __init__(self):
        self._tokens: dict[str, ActionApproval] = {}

    def issue(self, request: ActionRequest, *, ttl_seconds: float = 60.0) -> ActionApproval:
        if not isinstance(request, ActionRequest):
            raise TypeError("Approval requires an immutable ActionRequest.")
        lifetime = max(1.0, min(float(ttl_seconds), 120.0))
        approval = ActionApproval(
            secrets.token_urlsafe(32), request.digest, time.monotonic() + lifetime
        )
        self._tokens[approval.token] = approval
        return approval

    def consume(self, request: ActionRequest, approval: ActionApproval | None) -> bool:
        if not isinstance(request, ActionRequest) or not isinstance(approval, ActionApproval):
            return False
        stored = self._tokens.get(approval.token)
        if stored != approval:
            return False
        if stored.expires_at < time.monotonic():
            self._tokens.pop(approval.token, None)
            return False
        if stored.request_digest != request.digest:
            return False
        self._tokens.pop(approval.token, None)
        return True


__all__ = ["ActionApproval", "ActionApprovalStore"]
