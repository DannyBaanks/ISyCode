"""One external publication, approved for one remote and one content digest.

The model has no tool that calls this owner. There is no default transport:
without the caller supplying one, and without a fresh approval of that exact
remote, ref and digest, nothing is contacted. A local commit stays on
``GitOwner`` and does not reach this path.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

OWNER_ID = "workspace_publish"
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def remote_is_exact(remote: str) -> bool:
    parsed = urlsplit(remote)
    return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path not in {"", "/"} and ".." not in parsed.path.split("/"))


@dataclass(frozen=True)
class PublishPreview:
    request: ActionRequest
    remote: str
    ref: str
    content_sha256: str


class PublishOwner:
    """The only owner of ``git.push``. It never shells out to git."""

    def __init__(self, root: Path, authority: WorkspaceAuthority, approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id=OWNER_ID)

    def prepare(self, remote: str, ref: str, content_sha256: str) -> PublishPreview:
        if not remote_is_exact(remote) or not isinstance(ref, str) or _REF.fullmatch(ref) is None:
            raise ValueError("publication needs one https remote and one ref")
        if not isinstance(content_sha256, str) or _DIGEST.fullmatch(content_sha256) is None:
            raise ValueError("publication content digest is invalid")
        request = ActionRequest(
            "git.push", self.root, remote,
            {"remote": remote, "ref": ref, "content_sha256": content_sha256},
            execution_owner="workspace_publish")
        return PublishPreview(request, remote, ref, content_sha256)

    def run(self, preview: PublishPreview, approval: ActionApproval | None,
            transport: Callable[[str, str, str], None] | None) -> ActionOutcome:
        request = preview.request
        if (preview.remote != request.parameters["remote"]
                or preview.ref != request.parameters["ref"]
                or preview.content_sha256 != request.parameters["content_sha256"]
                or request.target != preview.remote):
            return ActionOutcome("Publication denied.", "DENY", None,
                                 "publication no longer matches the reviewed request")
        _, decision = self.gate.authorize(request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            return ActionOutcome("Publication denied.", "DENY", None,
                                 "; ".join(check.reason for check in decision.checks if not check.passed)
                                 or "publication was not authorized")
        if transport is None:
            return ActionOutcome("Publication denied.", "DENY", None,
                                 "no publication transport is registered")
        transport(preview.remote, preview.ref, preview.content_sha256)
        result = "published"
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "git.push", request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result) or not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Publication is not verifiable.", "NOT_VERIFIABLE", None,
                                 "durable publication receipt could not be persisted")
        return ActionOutcome(result, "ALLOW", receipt, "one approved remote and content digest")


__all__ = ["PublishOwner", "PublishPreview", "remote_is_exact"]
