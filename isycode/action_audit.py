"""Private, append-only audit journal for local ISyCode action decisions."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isycode.actions import ACTION_BY_ID
from isycode.security import ActionRequest, AuthorityDecision, SentinelDecision
from isycode.workspace_setup import state_root


class ActionAuditError(RuntimeError):
    """The private action journal is unsafe, corrupt, or unavailable."""


@dataclass(frozen=True)
class ActionAuditReport:
    status: str
    records: int
    decisions: int
    receipts: int
    unverifiable: int
    recent: tuple[dict[str, Any], ...]
    reason: str = ""


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

    @classmethod
    def for_read_only_inspection(cls, workspace_root: Path,
                                 *, state_directory: Path | None = None) -> "ActionAuditJournal":
        """Build a verifier handle without creating or changing state files."""
        root = Path(workspace_root).expanduser().resolve(strict=True)
        root_id = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]
        directory = Path(state_directory or (state_root() / "action-audit")).expanduser()
        instance = cls.__new__(cls)
        instance.path = directory / f"actions-{root_id}.jsonl"
        return instance

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

    def verify(self, *, recent_limit: int = 80) -> ActionAuditReport:
        """Verify the journal without repairing, rewriting, or following links."""
        if not isinstance(recent_limit, int) or not 0 <= recent_limit <= 500:
            raise ValueError("recent_limit must be between 0 and 500")
        try:
            parent_info = self.path.parent.lstat()
        except FileNotFoundError:
            return ActionAuditReport("NOT_VERIFIABLE", 0, 0, 0, 0, (),
                                     "no durable journal exists for this workspace")
        except OSError:
            return ActionAuditReport("JOURNAL_INVALID", 0, 0, 0, 0, (),
                                     "journal directory metadata is unavailable")
        if (not stat.S_ISDIR(parent_info.st_mode) or self.path.parent.is_symlink()
                or (os.name == "posix" and
                    (parent_info.st_uid != os.getuid() or parent_info.st_mode & 0o077))):
            return ActionAuditReport("JOURNAL_INVALID", 0, 0, 0, 0, (),
                                     "journal directory is unsafe")
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return ActionAuditReport("NOT_VERIFIABLE", 0, 0, 0, 0, (),
                                     "no durable journal exists for this workspace")
        except OSError:
            return ActionAuditReport("JOURNAL_INVALID", 0, 0, 0, 0, (),
                                     "journal metadata is unavailable")
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size > self.MAX_BYTES
                or (os.name == "posix" and
                    (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            return ActionAuditReport("JOURNAL_INVALID", 0, 0, 0, 0, (),
                                     "journal file is unsafe or exceeds its size limit")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
            try:
                opened = os.fstat(fd)
                if (not stat.S_ISREG(opened.st_mode) or opened.st_ino != info.st_ino
                        or opened.st_dev != info.st_dev or opened.st_size > self.MAX_BYTES):
                    raise ValueError("journal changed during verification")
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 64 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(fd)
                if (after.st_size != opened.st_size
                        or after.st_mtime_ns != opened.st_mtime_ns
                        or after.st_ctime_ns != opened.st_ctime_ns):
                    raise ValueError("journal changed during verification")
            finally:
                os.close(fd)
            raw = b"".join(chunks)
            if len(raw) > self.MAX_BYTES or (raw and not raw.endswith(b"\n")):
                raise ValueError("journal is truncated or exceeds its size limit")
            lines = raw.decode("utf-8").splitlines()
            previous = "0" * 64
            decisions_by_digest: dict[str, list[tuple[str, str, bool]]] = {}
            receipt_ids: set[str] = set()
            records: list[dict[str, Any]] = []
            decisions = receipts = unverifiable = 0
            for line_number, line in enumerate(lines, 1):
                if len(line.encode("utf-8")) > self.MAX_RECORD_BYTES:
                    raise ValueError(f"record {line_number} exceeds the record limit")
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"record {line_number} is not an object")
                digest = record.get("digest")
                body = {key: value for key, value in record.items() if key != "digest"}
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(char not in "0123456789abcdef" for char in digest)
                        or body.get("previous") != previous):
                    raise ValueError(f"record {line_number} has invalid chain metadata")
                canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"))
                expected = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
                if not hmac.compare_digest(digest, expected):
                    raise ValueError(f"record {line_number} digest mismatch")
                kind = body.get("kind")
                action = body.get("action")
                owner = body.get("owner")
                request_digest = body.get("request_digest")
                if (kind not in {"decision", "receipt"} or action not in ACTION_BY_ID
                        or not isinstance(owner, str) or len(owner) > 120
                        or not isinstance(request_digest, str) or len(request_digest) != 64
                        or any(char not in "0123456789abcdef" for char in request_digest)
                        or not isinstance(body.get("time"), (int, float))
                        or not isinstance(body.get("workspace"), str)
                        or len(body["workspace"]) != 32):
                    raise ValueError(f"record {line_number} has invalid identity or structure")
                version = body.get("version")
                if version not in {None, 1}:
                    raise ValueError(f"record {line_number} has an unsupported format version")
                if version is None:
                    unverifiable += 1
                if kind == "decision":
                    if (not isinstance(body.get("authority"), bool)
                            or body.get("sentinel") not in {"ALLOW", "DENY"}
                            or not isinstance(body.get("failed_checks"), list)
                            or not all(isinstance(item, str) for item in body["failed_checks"])):
                        raise ValueError(f"decision {line_number} has invalid status fields")
                    # A frozen request can be re-evaluated after grant state changes.
                    # Keep each chronological decision; a later DENY does not erase an
                    # earlier successful execution receipt.
                    decisions_by_digest.setdefault(request_digest, []).append(
                        (action, owner, body["authority"] and body["sentinel"] == "ALLOW"))
                    decisions += 1
                    if not owner:
                        unverifiable += 1
                else:
                    receipt_id = body.get("receipt_id")
                    result_digest = body.get("result_digest")
                    decision_bindings = decisions_by_digest.get(request_digest, [])
                    if (not isinstance(receipt_id, str) or not receipt_id
                            or receipt_id in receipt_ids
                            or not isinstance(result_digest, str) or len(result_digest) != 64
                            or any(char not in "0123456789abcdef" for char in result_digest)
                            or (action, owner, True) not in decision_bindings):
                        raise ValueError(f"receipt {line_number} is invalid, replayed, or unbound")
                    receipt_ids.add(receipt_id)
                    receipts += 1
                    if not owner:
                        unverifiable += 1
                records.append(body)
                previous = digest
            safe_recent = tuple({
                "kind": item["kind"], "time": item["time"], "action": item["action"],
                "owner": item["owner"], "request_digest": item["request_digest"],
                "authority": item.get("authority"), "sentinel": item.get("sentinel"),
                "failed_checks": item.get("failed_checks", []),
                "receipt_id": item.get("receipt_id"),
                "result_digest": item.get("result_digest"),
            } for item in records[-recent_limit:] if recent_limit)
            status = "NOT_VERIFIABLE" if unverifiable else "PASS"
            return ActionAuditReport(status, len(records), decisions, receipts,
                                     unverifiable, safe_recent)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return ActionAuditReport("JOURNAL_INVALID", 0, 0, 0, 0, (),
                                     f"journal verification failed ({type(exc).__name__})")

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
            body.setdefault("version", 1)
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


__all__ = ["ActionAuditError", "ActionAuditJournal", "ActionAuditReport"]
