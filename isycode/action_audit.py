"""Private, append-only audit journal for local ISyCode action decisions."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from isycode.security import ActionRequest, AuthorityDecision, SentinelDecision
from isycode.workspace_setup import state_root


class ActionAuditError(RuntimeError):
    """The private action journal is unsafe, corrupt, or unavailable."""


class ActionAuditJournal:
    """Hash-chain authorization and receipt metadata outside the workspace.

    Prompts, request parameters, targets, file contents, and credentials are
    deliberately excluded. If the journal cannot accept a decision, the
    action gate must fail closed.
    """

    MAX_BYTES = 16 * 1024 * 1024
    MAX_RECORD_BYTES = 16 * 1024

    def __init__(self, workspace_root: Path, *, state_directory: Path | None = None):
        root = Path(workspace_root).expanduser().resolve(strict=True)
        root_id = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]
        directory = Path(state_directory or (state_root() / "action-audit")).expanduser()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or not directory.is_dir():
            raise ActionAuditError("private action journal directory is unsafe")
        directory = directory.resolve(strict=True)
        if os.name == "posix":
            directory.chmod(0o700)
        self.path = directory / f"actions-{root_id}.jsonl"

    def record_decision(self, request: ActionRequest, authority: AuthorityDecision,
                        decision: SentinelDecision) -> None:
        if not isinstance(request, ActionRequest) or not isinstance(decision, SentinelDecision):
            raise ActionAuditError("action decision is malformed")
        failed = [check.name[:120] for check in decision.checks if not check.passed]
        self._append({
            "kind": "decision", "time": time.time(),
            "workspace": hashlib.sha256(str(request.workspace_root).encode()).hexdigest()[:32],
            "action": request.action_id, "owner": request.execution_owner,
            "request_digest": request.digest,
            "authority": bool(isinstance(authority, AuthorityDecision) and authority.allowed),
            "sentinel": decision.status, "failed_checks": failed[:64],
        })

    def record_receipt(self, request: ActionRequest, receipt: Any) -> None:
        if not isinstance(request, ActionRequest):
            raise ActionAuditError("action receipt request is malformed")
        receipt_action = getattr(receipt, "action_id", None)
        action_matches = receipt_action == request.action_id or (
            request.action_id == "broker.start"
            and request.execution_owner == "broker_provision"
            and receipt_action == "broker.build+broker.start"
        )
        if (getattr(receipt, "request_digest", None) != request.digest
                or not action_matches
                or getattr(receipt, "decision", None) != "ALLOW"
                or getattr(receipt, "outcome", None) != "SUCCESS"):
            raise ActionAuditError("action receipt does not match its request")
        self._append({
            "kind": "receipt", "time": time.time(),
            "workspace": hashlib.sha256(str(request.workspace_root).encode()).hexdigest()[:32],
            "action": request.action_id, "owner": request.execution_owner,
            "request_digest": request.digest,
            "receipt_id": str(receipt.receipt_id)[:160],
            "result_digest": str(receipt.result_digest)[:128],
        })

    def _append(self, body: dict[str, Any]) -> None:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX fallback uses exclusive file access
            fcntl = None
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise ActionAuditError("private action journal cannot be opened") from exc
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_size > self.MAX_BYTES
                    or (os.name == "posix" and info.st_uid != os.getuid())):
                raise ActionAuditError("private action journal is unsafe or full")
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            os.lseek(fd, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            remaining = self.MAX_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > self.MAX_BYTES:
                raise ActionAuditError("private action journal is full")
            previous = "0" * 64
            if raw:
                try:
                    lines = raw.decode("utf-8").splitlines()
                    if not lines or raw and not raw.endswith(b"\n"):
                        raise ValueError("incomplete journal line")
                    for line in lines:
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            raise ValueError("journal record is not an object")
                        digest = record.pop("digest")
                        chained_from = record.get("previous")
                        if chained_from != previous:
                            raise ValueError("broken previous digest")
                        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":"))
                        expected = hashlib.sha256((previous + canonical).encode()).hexdigest()
                        if not isinstance(digest, str) or not hmac.compare_digest(digest, expected):
                            raise ValueError("invalid record digest")
                        previous = digest
                except (UnicodeError, json.JSONDecodeError, AttributeError, KeyError,
                        TypeError, ValueError) as exc:
                    raise ActionAuditError("private action journal integrity check failed") from exc
            body["previous"] = previous
            canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            body["digest"] = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
            encoded = (json.dumps(body, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")) + "\n").encode("utf-8")
            if len(encoded) > self.MAX_RECORD_BYTES or info.st_size + len(encoded) > self.MAX_BYTES:
                raise ActionAuditError("private action journal has reached its size limit")
            os.lseek(fd, 0, os.SEEK_END)
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short journal write")
                view = view[written:]
            os.fsync(fd)
        except ActionAuditError:
            raise
        except OSError as exc:
            raise ActionAuditError("private action journal could not be committed") from exc
        finally:
            if fcntl is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(fd)


__all__ = ["ActionAuditError", "ActionAuditJournal"]
