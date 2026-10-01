"""Short-lived, one-use human approval tokens bound to an ActionRequest."""
from __future__ import annotations

import math
import secrets
import threading
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

    MAX_PENDING_APPROVALS: int = 1024

    def __init__(self):
        self._tokens: dict[str, ActionApproval] = {}
        self._lock = threading.Lock()

    def issue(self, request: ActionRequest, *, ttl_seconds: float = 60.0) -> ActionApproval:
        if not isinstance(request, ActionRequest):
            raise TypeError("Approval requires an immutable ActionRequest.")
        try:
            requested_lifetime = float(ttl_seconds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Approval lifetime must be a finite number of seconds.") from exc
        if not math.isfinite(requested_lifetime):
            raise ValueError("Approval lifetime must be a finite number of seconds.")
        lifetime = max(1.0, min(requested_lifetime, 120.0))
        approval = ActionApproval(
            secrets.token_urlsafe(32), request.digest, time.monotonic() + lifetime
        )
        with self._lock:
            now = time.monotonic()
            self._tokens = {key: value for key, value in self._tokens.items()
                            if value.expires_at >= now}
            if len(self._tokens) >= self.MAX_PENDING_APPROVALS:
                raise RuntimeError("Too many pending approvals; wait for existing approvals to expire.")
            self._tokens[approval.token] = approval
        return approval

    def consume(self, request: ActionRequest, approval: ActionApproval | None) -> bool:
        if not isinstance(request, ActionRequest) or not isinstance(approval, ActionApproval):
            return False
        with self._lock:
            stored = self._tokens.get(approval.token)
            if stored is None or stored != approval:
                return False
            if stored.expires_at < time.monotonic():
                self._tokens.pop(approval.token, None)
                return False
            if stored.request_digest != request.digest:
                return False
            self._tokens.pop(approval.token, None)
            return True


__all__ = ["ActionApproval", "ActionApprovalStore"]
