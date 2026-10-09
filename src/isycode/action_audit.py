"""Private, append-only audit journal for local ISyCode action decisions."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isycode.actions import ACTION_BY_ID
from isycode.effect_policy import EFFECTS, POLICY_VERSION, effect_class
from isycode.security import ActionRequest, AuthorityDecision, DecisionCheck, SentinelDecision
from isycode.workspace_setup import state_root


# In-process observers of journaled decisions (the IsySentinel rail). They get
# a copy of the record exactly as written, only after it was durably appended,
# and they can never change, block or fail a decision.
_decision_listeners: list = []


def add_decision_listener(listener) -> None:
    if listener not in _decision_listeners:
        _decision_listeners.append(listener)


def remove_decision_listener(listener) -> None:
    if listener in _decision_listeners:
        _decision_listeners.remove(listener)


def _notify_decision(record: dict[str, Any]) -> None:
    for listener in list(_decision_listeners):
        try:
            listener(json.loads(json.dumps(record)))
        except Exception:  # an observer must never affect the action gate
            pass


class ActionAuditError(RuntimeError):
    """The private action journal is unsafe, corrupt, or unavailable."""


def _journal_effect(action_id: str) -> str:
    """Effect class recorded for one action, or a fail-closed error.

    The gate classifies an action before it records a decision, so an
    unclassified action reaching this point is a programming error and not a
    reason to write a decision whose meaning cannot be re-checked later.
    """
    try:
        return effect_class(action_id)
    except KeyError as exc:
        raise ActionAuditError("decision has no effect classification") from exc


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
    # The active file is sealed into a numbered segment at this size; the next
    # file starts with a "segment" record that anchors the sealed file's last
    # digest, byte digest and record count, so the hash chain spans segments.
    SEGMENT_BYTES = 4 * 1024 * 1024
    MAX_SEGMENTS = 100_000

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
        self.root_id = root_id

    @classmethod
    def for_read_only_inspection(cls, workspace_root: Path,
                                 *, state_directory: Path | None = None) -> "ActionAuditJournal":
        """Build a verifier handle without creating or changing state files."""
        root = Path(workspace_root).expanduser().resolve(strict=True)
        root_id = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]
        directory = Path(state_directory or (state_root() / "action-audit")).expanduser()
        instance = cls.__new__(cls)
        instance.path = directory / f"actions-{root_id}.jsonl"
        instance.root_id = root_id
        return instance

    # ── segments ───────────────────────────────────────────────

    def _segment_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.stem}.{index:06d}.jsonl")

    def _sealed_segments(self) -> list[Path]:
        """Sealed segments in order; gaps or unexpected names are corruption."""
        pattern = re.compile(rf"^{re.escape(self.path.stem)}\.(\d{{6}})\.jsonl$")
        try:
            names = os.listdir(self.path.parent)
        except FileNotFoundError:
            return []
        indexes = sorted(int(match.group(1)) for name in names
                         if (match := pattern.fullmatch(name)))
        if indexes != list(range(1, len(indexes) + 1)) or len(indexes) > self.MAX_SEGMENTS:
            raise ValueError("sealed journal segments are missing or out of order")
        return [self._segment_path(index) for index in indexes]

    def _read_private_file(self, path: Path) -> bytes:
        """Read one journal file without following links, bounded and stable."""
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size > self.MAX_BYTES
                or (os.name == "posix" and
                    (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            raise ValueError("journal file is unsafe or exceeds its size limit")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
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
            if (after.st_size != opened.st_size or after.st_mtime_ns != opened.st_mtime_ns
                    or after.st_ctime_ns != opened.st_ctime_ns):
                raise ValueError("journal changed during verification")
        finally:
            os.close(fd)
        raw = b"".join(chunks)
        if len(raw) > self.MAX_BYTES or (raw and not raw.endswith(b"\n")):
            raise ValueError("journal is truncated or exceeds its size limit")
        return raw

    @staticmethod
    def _chain_tail(raw: bytes) -> tuple[str, int]:
        """Last digest and record count of a complete, already-sealed segment."""
        lines = raw.decode("utf-8").splitlines()
        if not lines:
            raise ValueError("sealed journal segment is empty")
        last = json.loads(lines[-1])
        digest = last.get("digest") if isinstance(last, dict) else None
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("sealed journal segment has no valid tail digest")
        return digest, len(lines)

    def record_decision(self, request: ActionRequest, authority: AuthorityDecision,
                        decision: SentinelDecision, *, approval_mode: str | None = None) -> None:
        if (not isinstance(request, ActionRequest)
                or not isinstance(authority, AuthorityDecision)
                or not isinstance(decision, SentinelDecision)):
            raise ActionAuditError("action decision is malformed")
        if (authority.request_digest != request.digest
                or decision.action_id != request.action_id
                or decision.request_digest != request.digest):
            raise ActionAuditError("action decision does not match its immutable request")
        if (len(decision.checks) > 64 or any(
                not isinstance(check, DecisionCheck) or not isinstance(check.name, str)
                or not isinstance(check.passed, bool)
                for check in decision.checks)):
            raise ActionAuditError("action decision checks are malformed")
        if approval_mode not in {None, "user", "delegated"}:
            raise ActionAuditError("approval mode is malformed")
        failed = [check.name[:120] for check in decision.checks if not check.passed]
        record = {
            "kind": "decision", "time": time.time(),
            "workspace": hashlib.sha256(str(request.workspace_root).encode()).hexdigest()[:32],
            "action": request.action_id, "owner": request.execution_owner,
            "request_digest": request.digest,
            "authority": bool(isinstance(authority, AuthorityDecision) and authority.allowed),
            "sentinel": decision.status, "failed_checks": failed[:64],
            "checks": [{"name": check.name[:120], "passed": check.passed}
                       for check in decision.checks[:64]],
            # The taxonomy that classified this action and the policy version
            # that did it. Without them a later edit of the action catalog can
            # re-label an old decision, or move an action out of the Classic
            # preset, without leaving a trace in the journal.
            "effect": _journal_effect(request.action_id),
            "policy_version": POLICY_VERSION,
        }
        if approval_mode is not None:
            record["approval"] = approval_mode  # who approved: the user, or a setting they enabled
        self._append(record)
        _notify_decision(record)

    def record_receipt(self, request: ActionRequest, receipt: Any) -> None:
        if not isinstance(request, ActionRequest):
            raise ActionAuditError("action receipt request is malformed")
        receipt_action = getattr(receipt, "action_id", None)
        receipt_id = getattr(receipt, "receipt_id", None)
        result_digest = getattr(receipt, "result_digest", None)
        outcome = getattr(receipt, "outcome", None)
        valid_outcome = (outcome == "SUCCESS" or
                         (request.action_id in {"tailscale.install.prepare", "tailscale.install.stage", "tailscale.install", "tailscale.login", "tailscale.serve.enable", "tailscale.serve.disable"}
                          and outcome == "FAILURE"))
        action_matches = receipt_action == request.action_id or (
            request.action_id == "broker.start"
            and request.execution_owner == "broker_provision"
            and receipt_action == "broker.build+broker.start"
        )
        if (getattr(receipt, "request_digest", None) != request.digest
                or not action_matches
                or getattr(receipt, "decision", None) != "ALLOW"
                or not valid_outcome
                or not isinstance(receipt_id, str) or not receipt_id or len(receipt_id) > 160
                or not isinstance(result_digest, str) or len(result_digest) != 64
                or any(char not in "0123456789abcdef" for char in result_digest)):
            raise ActionAuditError("action receipt does not match its request")
        self._append({
            "kind": "receipt", "time": time.time(),
            "workspace": hashlib.sha256(str(request.workspace_root).encode()).hexdigest()[:32],
            "action": request.action_id, "owner": request.execution_owner,
            "request_digest": request.digest,
            "receipt_id": receipt_id,
            "result_digest": result_digest,
            "outcome": outcome,
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
            sealed = self._sealed_segments()
            files = sealed + ([self.path] if self.path.exists() or self.path.is_symlink() else [])
        except (OSError, ValueError):
            return ActionAuditReport("JOURNAL_INVALID", 0, 0, 0, 0, (),
                                     "journal segments are missing or out of order")
        if not files:
            return ActionAuditReport("NOT_VERIFIABLE", 0, 0, 0, 0, (),
                                     "no durable journal exists for this workspace")
        try:
            raws = [self._read_private_file(path) for path in files]
        except (OSError, ValueError):
            return ActionAuditReport("JOURNAL_INVALID", 0, 0, 0, 0, (),
                                     "journal file is unsafe or exceeds its size limit")
        try:
            lines: list[str] = []
            boundaries: dict[int, tuple[int, bytes, int]] = {}
            for index, raw in enumerate(raws):
                if index:
                    # The first line of each later file must anchor the file before it.
                    boundaries[len(lines) + 1] = (index, raws[index - 1],
                                                  len(raws[index - 1].decode("utf-8").splitlines()))
                lines.extend(raw.decode("utf-8").splitlines())
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
                boundary = boundaries.get(line_number)
                if kind == "segment" or boundary is not None:
                    if (kind != "segment" or boundary is None
                            or body.get("sealed_index") != boundary[0]
                            or body.get("sealed_sha256") != hashlib.sha256(boundary[1]).hexdigest()
                            or body.get("sealed_records") != boundary[2]
                            or body.get("workspace") != getattr(self, "root_id", body.get("workspace"))):
                        raise ValueError(f"record {line_number} is not a valid segment anchor")
                    previous = digest
                    continue
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
                # Effect identity is optional so journals written before it
                # existed keep verifying; when present it must be valid, or a
                # forged label would pass as a recorded decision.
                effect = body.get("effect")
                if effect is not None and effect not in EFFECTS:
                    raise ValueError(f"record {line_number} has an unknown effect class")
                policy_version = body.get("policy_version")
                if policy_version is not None and policy_version != POLICY_VERSION:
                    raise ValueError(f"record {line_number} has an unsupported policy version")
                if kind == "decision":
                    if (not isinstance(body.get("authority"), bool)
                            or body.get("sentinel") not in {"ALLOW", "DENY"}
                            or not isinstance(body.get("failed_checks"), list)
                            or not all(isinstance(item, str) for item in body["failed_checks"])):
                        raise ValueError(f"decision {line_number} has invalid status fields")
                    checks = body.get("checks")
                    if checks is None:
                        unverifiable += 1
                        checks = []
                    if (not isinstance(checks, list) or len(checks) > 64
                            or any(not isinstance(item, dict)
                                   or not isinstance(item.get("name"), str)
                                   or len(item["name"]) > 120
                                   or not isinstance(item.get("passed"), bool)
                                   for item in checks)):
                        raise ValueError(f"decision {line_number} has invalid check metadata")
                    if body.get("approval") not in {None, "user", "delegated"}:
                        raise ValueError(f"decision {line_number} has an invalid approval mode")
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
                    outcome = body.get("outcome", "SUCCESS")
                    decision_bindings = decisions_by_digest.get(request_digest, [])
                    if (not isinstance(receipt_id, str) or not receipt_id
                            or receipt_id in receipt_ids
                            or (outcome != "SUCCESS" and
                                not (action in {"tailscale.install.prepare", "tailscale.install.stage", "tailscale.install", "tailscale.login", "tailscale.serve.enable", "tailscale.serve.disable"}
                                     and outcome == "FAILURE"))
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
                "checks": item.get("checks", []),
                "effect": item.get("effect"),
                "approval": item.get("approval"),
                "receipt_id": item.get("receipt_id"),
                "result_digest": item.get("result_digest"),
                "outcome": item.get("outcome", "SUCCESS") if item["kind"] == "receipt" else None,
            } for item in records[-recent_limit:] if recent_limit)
            status = "NOT_VERIFIABLE" if unverifiable else "PASS"
            return ActionAuditReport(status, len(records), decisions, receipts,
                                     unverifiable, safe_recent)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return ActionAuditReport("JOURNAL_INVALID", 0, 0, 0, 0, (),
                                     f"journal verification failed ({type(exc).__name__})")

    def _append(self, body: dict[str, Any]) -> None:
        # A concurrent writer may seal the active file between our open and our
        # lock; _append_once then reports "rotated" and we reopen the new file.
        for _ in range(4):
            if self._append_once(dict(body)):
                return
        raise ActionAuditError("private action journal kept rotating; action denied")

    def _append_once(self, body: dict[str, Any]) -> bool:
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
            try:
                current = self.path.lstat()
            except FileNotFoundError:
                return False
            if (current.st_ino, current.st_dev) != (info.st_ino, info.st_dev):
                return False
            info = os.fstat(fd)
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
            pending: list[dict[str, Any]] = []
            if not raw:
                try:
                    sealed = self._sealed_segments()
                    if sealed:
                        sealed_raw = self._read_private_file(sealed[-1])
                        tail, count = self._chain_tail(sealed_raw)
                        pending.append({
                            "kind": "segment", "time": time.time(), "workspace": self.root_id,
                            "sealed_index": len(sealed),
                            "sealed_sha256": hashlib.sha256(sealed_raw).hexdigest(),
                            "sealed_records": count,
                        })
                        previous = tail
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    raise ActionAuditError("sealed journal segments cannot be anchored") from exc
            if raw:
                try:
                    lines = raw.decode("utf-8").splitlines()
                    if not lines or raw and not raw.endswith(b"\n"):
                        raise ValueError("incomplete journal line")
                    first = json.loads(lines[0])
                    if isinstance(first, dict) and first.get("kind") == "segment":
                        anchor = first.get("previous")
                        if not isinstance(anchor, str) or re.fullmatch(r"[0-9a-f]{64}", anchor) is None:
                            raise ValueError("invalid segment anchor")
                        previous = anchor
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
            encoded = b""
            for record in pending + [body]:
                record["previous"] = previous
                record.setdefault("version", 1)
                canonical = json.dumps(record, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"))
                record["digest"] = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
                line = (json.dumps(record, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")) + "\n").encode("utf-8")
                if len(line) > self.MAX_RECORD_BYTES:
                    raise ActionAuditError("private action journal record exceeds its limit")
                encoded += line
                previous = record["digest"]
            if raw and info.st_size + len(encoded) > self.SEGMENT_BYTES:
                sealed_count = len(self._sealed_segments())
                target = self._segment_path(sealed_count + 1)
                if target.exists() or target.is_symlink():
                    raise ActionAuditError("private action journal segment already exists")
                os.fsync(fd)
                os.rename(self.path, target)
                return False
            if info.st_size + len(encoded) > self.MAX_BYTES:
                raise ActionAuditError("private action journal has reached its size limit")
            os.lseek(fd, 0, os.SEEK_END)
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short journal write")
                view = view[written:]
            os.fsync(fd)
            return True
        except ActionAuditError:
            raise
        except (OSError, ValueError) as exc:
            raise ActionAuditError("private action journal could not be committed") from exc
        finally:
            if fcntl is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(fd)


__all__ = ["ActionAuditError", "ActionAuditJournal", "ActionAuditReport"]
