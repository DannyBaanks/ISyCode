"""Approved, diff-previewed writes of one UTF-8 text file inside the workspace.

The model may only *propose* a full new file content. The owner turns that into
an exact unified diff and an ActionRequest bound to the digests of the current
and proposed content. Nothing is written until Workspace Authority (explicit
path-scoped grant plus a fresh one-use approval) and IsySentinel allow that
exact request; the file is then replaced atomically through directory handles
that never follow symlinks, re-read, and journaled with a receipt.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

from isycode.action_runtime import (
    MAX_WRITE_BYTES, ActionOutcome, ActionReceipt, ProductActionGate,
    WorkspaceReadSystembility,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

WRITE_TOOL_NAME = "workspace_write"
WRITE_TOOL = {"type": "function", "function": {
    "name": WRITE_TOOL_NAME,
    "description": ("Propose replacing one UTF-8 text file (up to 128 KiB) in the workspace with "
                    "the complete new content, or creating it in an existing folder. The user "
                    "reviews the exact diff and must approve; the result says whether it was "
                    "written or rejected."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Workspace-relative file path."},
        "content": {"type": "string", "description": "The complete new file content."},
    }, "required": ["path", "content"], "additionalProperties": False},
}}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class WritePreview:
    request: ActionRequest
    path: str
    diff: str
    created: bool
    content: str = field(repr=False)


class WorkspaceWriteOwner:
    """Replace one text file only after its exact diff is authorized and approved."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="workspace_write")

    # ── preview ────────────────────────────────────────────────

    def _target(self, path: str) -> Path:
        if not isinstance(path, str) or not path.strip() or len(path) > 4096 or "\0" in path:
            raise ValueError("path must be a bounded workspace-relative string")
        raw = Path(path).expanduser()
        lexical = Path(os.path.abspath(raw if raw.is_absolute() else self.root / raw))
        if self.root not in lexical.parents:
            raise ValueError("path must name a file inside the workspace")
        relative = lexical.relative_to(self.root)
        if any(WorkspaceReadSystembility.is_sensitive_name(part) for part in relative.parts):
            raise ValueError("sensitive paths cannot be written")
        return lexical

    def preview(self, path: str, content: str) -> WritePreview:
        """Compute the exact diff and request; performs reads only, never writes."""
        if not isinstance(content, str):
            raise ValueError("content must be text")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_WRITE_BYTES:
            raise ValueError("content exceeds the 128 KiB write limit")
        target = self._target(path)
        relative = target.relative_to(self.root).as_posix()
        parent_fd = self._open_directory(target.parent)
        try:
            before = self._read_at(parent_fd, target.name)
        finally:
            os.close(parent_fd)
        if before == encoded:
            raise ValueError("the file already has exactly this content")
        before_text = "" if before is None else before.decode("utf-8")
        diff = "".join(difflib.unified_diff(
            before_text.splitlines(keepends=True), content.splitlines(keepends=True),
            fromfile="/dev/null" if before is None else f"a/{relative}",
            tofile=f"b/{relative}", n=3))
        request = ActionRequest("workspace.files.write", self.root, str(target), {
            "path": relative,
            "before_sha256": "absent" if before is None else _sha(before),
            "after_sha256": _sha(encoded),
            "size": len(encoded),
            "diff_sha256": _sha(diff.encode("utf-8")),
        }, execution_owner="workspace_write")
        return WritePreview(request, relative, diff, before is None, content)

    # ── apply ──────────────────────────────────────────────────

    def apply(self, preview: WritePreview, approval: ActionApproval | None) -> ActionOutcome:
        if not isinstance(preview, WritePreview):
            return ActionOutcome("File change denied.", "DENY", None, "preview has the wrong type")
        try:
            fresh = self.preview(preview.path, preview.content)
        except (OSError, ValueError) as exc:
            return ActionOutcome("File change denied.", "DENY", None,
                                 f"file cannot be re-checked: {str(exc)[:200]}")
        if fresh.request != preview.request:
            return ActionOutcome("File change denied.", "DENY", None,
                                 "the file changed since the reviewed diff; review a new one")
        try:
            authority, decision = self.gate.authorize(
                preview.request, approvals=self.approvals, approval=approval)
        except Exception:
            return ActionOutcome("File change denied.", "DENY", None,
                                 "authorization evaluation failed")
        if not authority.allowed or not decision.allowed:
            reason = authority.reason if not authority.allowed else "; ".join(
                f"{item.name}: {item.reason}" for item in decision.checks if not item.passed)
            return ActionOutcome("File change denied.", "DENY", None, reason[:300])

        params = preview.request.parameters
        target = Path(preview.request.target)
        try:
            self._replace(target, preview.content.encode("utf-8"), params["before_sha256"])
            written = self._read_back(target)
            if written is None or _sha(written) != params["after_sha256"]:
                raise ValueError("written content does not match the approved digest")
        except (OSError, ValueError) as exc:
            receipt = self._receipt(preview.request, "FAILURE", "write_failed")
            return ActionOutcome("File change failed; the approved content is not verified.",
                                 "ERROR", receipt, str(exc)[:300])
        result = json.dumps({"path": params["path"], "after_sha256": params["after_sha256"]},
                            sort_keys=True)
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), preview.request.action_id,
                                preview.request.digest, "ALLOW", "SUCCESS",
                                _sha(result.encode("utf-8")))
        if not self.gate.persist_receipt(preview.request, receipt):
            return ActionOutcome("File written, but its receipt could not be journaled.",
                                 "NOT_VERIFIABLE", None, "durable action journal is unavailable")
        return ActionOutcome(f"Wrote {params['path']}", "ALLOW", receipt,
                             "reviewed diff applied and verified")

    def _receipt(self, request: ActionRequest, outcome: str, event: str) -> ActionReceipt | None:
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", outcome,
                                _sha(f"{outcome}:{event}".encode()))
        return receipt if self.gate.persist_receipt(request, receipt) else None

    # ── descriptor-safe filesystem helpers ─────────────────────

    def _open_directory(self, directory: Path) -> int:
        if os.name == "nt" or os.open not in os.supports_dir_fd:
            raise OSError("descriptor-safe workspace writes are not available on this platform")
        relative = directory.relative_to(self.root)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.root, flags)
        try:
            for part in relative.parts:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    @staticmethod
    def _read_at(parent_fd: int, name: str) -> bytes | None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("only regular files can be written")
            if info.st_size > MAX_WRITE_BYTES:
                raise ValueError("existing file exceeds the 128 KiB write limit")
            data = os.read(descriptor, MAX_WRITE_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(data) > MAX_WRITE_BYTES:
            raise ValueError("existing file exceeds the 128 KiB write limit")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("existing file is not UTF-8 text") from exc
        return data

    def _read_back(self, target: Path) -> bytes | None:
        parent_fd = self._open_directory(target.parent)
        try:
            return self._read_at(parent_fd, target.name)
        finally:
            os.close(parent_fd)

    def _replace(self, target: Path, data: bytes, expected_before: str) -> None:
        parent_fd = self._open_directory(target.parent)
        temporary = f".{target.name}.isycode-{secrets.token_hex(6)}.tmp"
        created = False
        try:
            current = self._read_at(parent_fd, target.name)
            if ("absent" if current is None else _sha(current)) != expected_before:
                raise ValueError("the file changed during approval; nothing was written")
            mode = 0o644
            if current is not None:
                mode = stat.S_IMODE(os.stat(target.name, dir_fd=parent_fd,
                                            follow_symlinks=False).st_mode)
            flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
            descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
            created = True
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(descriptor, view):]
                os.fchmod(descriptor, mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            created = False
            os.fsync(parent_fd)
        finally:
            if created:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except OSError:
                    pass
            os.close(parent_fd)


__all__ = ["WRITE_TOOL", "WRITE_TOOL_NAME", "WorkspaceWriteOwner", "WritePreview"]
