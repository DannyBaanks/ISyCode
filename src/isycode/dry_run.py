"""Pure request preview over Workspace Authority and IsySentinel."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from isycode.action_runtime import ProductActionGate
from isycode.actions import ACTION_BY_ID
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


@dataclass(frozen=True)
class DryRunResult:
    status: str
    exit_code: int
    action_id: str
    request_digest: str
    grant_id: str
    approval_required: bool
    reason: str
    checks: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "action_id": self.action_id,
            "request_digest": self.request_digest,
            "grant_id": self.grant_id,
            "approval_required": self.approval_required,
            "reason": self.reason,
            "checks": list(self.checks),
        }


def preview_request(root: Path, owner_id: str, request: ActionRequest) -> DryRunResult:
    """Return ALLOW/ASK/DENY without a journal write or effect."""
    canonical = Path(root).resolve(strict=True)
    authority = WorkspaceAuthority(canonical)
    gate = ProductActionGate(canonical, authority, owner_id=owner_id, journal=False)
    authority_result, sentinel = gate.preview(request)
    checks = tuple({"name": check.name, "passed": check.passed, "reason": check.reason}
                   for check in sentinel.checks)
    if not sentinel.allowed:
        reason = next((str(item["reason"]) for item in checks if not item["passed"]),
                      authority_result.reason or "request denied")
        return DryRunResult("DENY", 3, request.action_id, request.digest, "", False,
                            reason, checks)
    spec = ACTION_BY_ID.get(request.action_id)
    needs_approval = bool(spec and spec.approval_required)
    if needs_approval:
        return DryRunResult(
            "ASK", 4, request.action_id, request.digest, authority_result.grant_id, True,
            "fresh request-bound approval would be required before execution", checks,
        )
    return DryRunResult(
        "ALLOW", 0, request.action_id, request.digest, authority_result.grant_id, False,
        authority_result.reason or "request would be allowed", checks,
    )


__all__ = ["DryRunResult", "preview_request"]
