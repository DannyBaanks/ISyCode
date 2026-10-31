"""GUS's user-wide conversation and memory (ADR 0015, phase 3).

The conversation and the memories are the person's, not the workspace's: both
live in ISyCode's private state under ``<state>/gus``, outside every checkout
and outside the machine view's scope. They are shared across workspaces, like
a hosted assistant's history, and never enter a repository.

Two owners guard the data. ``GusMemoryStore`` is the bounded private file
(500 memories, 256 KiB); ``GusConversation`` is the shared transcript (80
entries, 32k characters). ``GusMemoryOwner`` is the only writer of memories:
it goes through Workspace Authority's pattern, IsySentinel, the effect ledger,
the journal and receipts. In ``explicit`` mode a write needs a one-use human
approval issued during the turn; in ``automatic`` mode the consented mode is
the authorization. Deleting is never the model's: ``gus.memory.forget`` is a
human tool and always needs an approval, and no GUS tool maps to it.

Every memory is redacted before it is stored: PEM blocks, API tokens, JWTs and
secret assignments are replaced or refused, and a memory with nothing useful
left is rejected. The text is still data, never instructions; the request
planner frames it that way.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest, AuthorityDecision
from isycode.state_index import get_state_index
from isycode.tool_history import sanitize_historical_text

OWNER_ID = "gus_memory"
RECORD_VERSION = 1
MEMORY_ACTION = "gus.memory.write"
FORGET_ACTION = "gus.memory.forget"
MEMBER_ACTIONS = frozenset({MEMORY_ACTION, FORGET_ACTION})
OPERATION_ACTION = {"remember": MEMORY_ACTION, "forget": FORGET_ACTION, "clear": FORGET_ACTION}
AUTOMATIC, EXPLICIT = "automatic", "explicit"
MEMORY_MODES = frozenset({AUTOMATIC, EXPLICIT})

MAX_MEMORIES = 500
MAX_RECORD_BYTES = 256 * 1024
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_MEMORY_CHARS = 4_000
MAX_MEMORIES_INJECTED = 20
MAX_CONVERSATION_ENTRIES = 80
MAX_CONVERSATION_CHARS = 32_000
MAX_ENTRY_CHARS = 32_000
MAX_CONVERSATION_BYTES = 256 * 1024
REDACTED = "[redacted]"
_IDENTIFIER = re.compile(r"^[0-9a-f]{32}$")
_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]{1,40}-----.*?-----END [A-Z0-9 ]{1,40}-----", re.DOTALL)
_SECRET_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"sk-[A-Za-z0-9_-]{8,}"
    r"|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{12,}"
    r"|eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"
    r")")


class GusMemoryError(ValueError):
    """The memory record or the operation cannot be used safely."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _useful(text: str) -> bool:
    return any(character.isalnum() for character in text.replace(REDACTED, " "))


def redact_memory(text: str) -> str:
    """Redact secrets from one memory; refuse text with nothing usable left.

    Detection is by shape — PEM blocks, provider tokens, JWTs and the secret
    assignments ``sanitize_historical_text`` already knows. A secret written
    without any of those shapes is a residual risk stated in ADR 0015.
    """
    if not isinstance(text, str) or "\0" in text:
        raise GusMemoryError("a memory must be bounded text")
    clean = _PEM_BLOCK.sub(REDACTED, text)
    clean = _SECRET_TOKEN.sub(REDACTED, clean)
    clean = sanitize_historical_text(clean).strip()
    if not _useful(clean):
        raise GusMemoryError("a memory has no usable content after redaction")
    if len(clean) > MAX_MEMORY_CHARS:
        clean = clean[:MAX_MEMORY_CHARS]
    return clean


class _PrivateRecord:
    """One bounded, private JSON record under the user's GUS state."""

    # Windows holds the target of an in-flight replace for milliseconds; a lock
    # that outlasts this window is treated as unreadable, not as a race.
    TRANSIENT_WINDOW_SECONDS = 0.25
    TRANSIENT_PAUSE_SECONDS = 0.01

    def __init__(self, directory: Path, name: str, *, max_bytes: int) -> None:
        self.directory = directory
        self.path = directory / name
        self.max_bytes = max_bytes

    def ensure(self) -> None:
        from isycode.platform_storage import storage
        storage.ensure_directory(self.directory.parent, repair=True)
        storage.ensure_directory(self.directory, repair=True)
        if (self.directory.is_symlink() or not self.directory.is_dir()
                or not storage.private(self.directory)):
            raise GusMemoryError("GUS's user state directory is unsafe")

    def read(self) -> dict[str, Any] | None:
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise GusMemoryError("GUS's user state cannot be inspected") from exc
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size > self.max_bytes):
            raise GusMemoryError("GUS's user state is not a bounded regular file")
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise GusMemoryError("GUS's user state is not private")
        try:
            data = self._read_json()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GusMemoryError("GUS's user state is unreadable") from exc
        if not isinstance(data, dict) or data.get("version") != RECORD_VERSION:
            raise GusMemoryError("GUS's user state does not match this version")
        return data

    def _read_json(self) -> Any:
        """Parse the record, waiting out a writer's atomic replace.

        On Windows a concurrent ``os.replace`` can deny this read for a moment
        even though the writer is healthy. Only that denial is transient:
        unreadable or corrupt content is still raised, not retried.
        """
        deadline = time.monotonic() + self.TRANSIENT_WINDOW_SECONDS
        while True:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except PermissionError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(self.TRANSIENT_PAUSE_SECONDS, remaining))

    def write(self, record: dict[str, Any]) -> None:
        payload = json.dumps({"version": RECORD_VERSION, **record}, ensure_ascii=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > self.max_bytes:
            raise GusMemoryError("GUS's user state exceeds its size limit")
        self.ensure()
        temporary = self.directory / (".gus-" + os.urandom(8).hex() + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.replace(temporary, self.path)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


class GusConversation:
    """The person's GUS transcript, shared by every workspace."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._record = _PrivateRecord(get_state_index().subsystem("gus", root=root),
                                      "conversation.json", max_bytes=MAX_CONVERSATION_BYTES)

    def entries(self) -> list[dict[str, str]]:
        record = self._record.read() or {}
        entries = record.get("entries")
        if not isinstance(entries, list):
            return []
        clean = []
        for entry in entries:
            if (isinstance(entry, dict) and entry.get("role") in {"user", "assistant"}
                    and isinstance(entry.get("text"), str) and isinstance(entry.get("at"), str)):
                clean.append({"role": entry["role"], "text": entry["text"],
                              "at": entry["at"], "workspace": str(entry.get("workspace") or "")})
        return clean

    @staticmethod
    def _trim(entries: list[dict[str, str]]) -> list[dict[str, str]]:
        entries = entries[-MAX_CONVERSATION_ENTRIES:]
        while len(entries) > 1 and sum(len(entry["text"]) for entry in entries) \
                > MAX_CONVERSATION_CHARS:
            entries.pop(0)
        return entries

    def append(self, role: str, text: str, *, workspace: str) -> list[dict[str, str]]:
        if role not in {"user", "assistant"}:
            raise GusMemoryError("a conversation entry has an unsupported role")
        if not isinstance(text, str) or not text.strip():
            raise GusMemoryError("a conversation entry needs text")
        entries = self._trim(self.entries() + [{
            "role": role, "text": text[:MAX_ENTRY_CHARS], "at": _now(),
            "workspace": str(workspace)[:4096]}])
        self._record.write({"entries": entries})
        return entries

    def clear(self) -> None:
        self._record.write({"entries": []})


class GusMemoryStore:
    """The person's bounded GUS memories, one private JSON record."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._record = _PrivateRecord(get_state_index().subsystem("gus", root=root),
                                      "memories.json", max_bytes=MAX_RECORD_BYTES)

    @property
    def directory(self) -> Path:
        return self._record.directory

    def ensure(self) -> None:
        self._record.ensure()

    def entries(self) -> list[dict[str, str]]:
        record = self._record.read() or {}
        entries = record.get("entries")
        if not isinstance(entries, list):
            return []
        return [{"id": entry["id"], "text": entry["text"], "at": entry["at"],
                 "workspace": str(entry.get("workspace") or "")}
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
                and _IDENTIFIER.fullmatch(entry["id"]) and isinstance(entry.get("text"), str)
                and isinstance(entry.get("at"), str)]

    def add(self, text: str, *, workspace: str) -> dict[str, str]:
        clean = redact_memory(text)
        entries = self.entries()
        if len(entries) >= MAX_MEMORIES:
            raise GusMemoryError("GUS's memory is full; forget something first")
        entry = {"id": secrets.token_hex(16), "text": clean, "at": _now(),
                 "workspace": str(workspace)[:4096]}
        self._record.write({"entries": entries + [entry]})
        return entry

    def forget(self, memory_id: str) -> dict[str, Any]:
        if not isinstance(memory_id, str) or not _IDENTIFIER.fullmatch(memory_id):
            raise GusMemoryError("memory id is invalid")
        entries = self.entries()
        kept = [entry for entry in entries if entry["id"] != memory_id]
        if len(kept) == len(entries):
            raise GusMemoryError("memory was not found")
        self._record.write({"entries": kept})
        return {"id": memory_id, "forgotten": True}

    def clear(self) -> int:
        count = len(self.entries())
        self._record.write({"entries": []})
        return count

    def texts(self, *, limit: int = MAX_MEMORIES_INJECTED) -> list[str]:
        return [entry["text"] for entry in self.entries()[-limit:]]


def memory_texts(root: Path | None = None, *, limit: int = MAX_MEMORIES_INJECTED) -> list[str]:
    """The memories to put in a request; an unreadable store injects none."""
    try:
        return GusMemoryStore(root=root).texts(limit=limit)
    except (GusMemoryError, OSError):
        return []


@dataclass(frozen=True)
class MemoryPreview:
    request: ActionRequest
    operation: str
    arguments: dict[str, Any]
    text: str = ""


class GusMemoryBoundary:
    """Bind each memory operation to its owner and argument digest."""

    name = "GusMemoryBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> Any:
        from isycode.security import SystembilityResult
        params = request.parameters
        operation = params.get("operation")
        action_id = OPERATION_ACTION.get(operation) if isinstance(operation, str) else None
        valid = (
            request.execution_owner == OWNER_ID
            and request.action_id == action_id
            and set(params) == {"operation", "arguments_sha256", "size"}
            and isinstance(params.get("arguments_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", params["arguments_sha256"]) is not None
            and type(params.get("size")) is int
            and 0 <= params["size"] <= MAX_ARGUMENT_BYTES
            and len(request.target) <= 128
        )
        return SystembilityResult(self.name, valid,
                                  "one bounded, digest-bound GUS memory operation"
                                  if valid else "memory operation is not bound to its owner")


class GusMemoryAuthority:
    """Authorize GUS's own memory by consent, mode and the person's approval."""

    def __init__(self, root: Path, *, consented: bool, mode: str) -> None:
        self.root = Path(root).resolve(strict=True)
        self.consented = bool(consented)
        self.mode = mode if mode in MEMORY_MODES else EXPLICIT

    def write_requires_approval(self) -> bool:
        return self.mode != AUTOMATIC

    def evaluate(self, request: ActionRequest, *, approvals: ActionApprovalStore | None = None,
                 approval: ActionApproval | None = None,
                 preview: bool = False) -> AuthorityDecision:
        reason = self._refusal(request, approvals, approval, preview)
        if reason:
            return AuthorityDecision(False, "", reason, request.digest)
        return AuthorityDecision(True, "gus-memory",
                                 "GUS memory is enabled for this person", request.digest)

    def _refusal(self, request: ActionRequest, approvals: ActionApprovalStore | None,
                 approval: ActionApproval | None, preview: bool) -> str:
        if request.workspace_root != self.root:
            return "GUS memory belongs to another state root"
        if not self.consented:
            return "GUS has no consent record for this person's memory"
        if preview:
            return ""
        operation = request.parameters.get("operation")
        if request.action_id == MEMORY_ACTION:
            from isycode.gus_l0 import gus_any_turn_active
            if operation != "remember":
                return "a GUS memory write must remember"
            if not gus_any_turn_active():
                return "GUS memory is written only inside a GUS turn"
            if self.write_requires_approval() \
                    and not (approvals is not None and approvals.consume(request, approval)):
                return "the person did not approve this memory"
            return ""
        if request.action_id == FORGET_ACTION:
            if operation not in {"forget", "clear"}:
                return "a GUS memory deletion must forget or clear"
            if not (approvals is not None and approvals.consume(request, approval)):
                return "forgetting a memory needs the person's approval"
            return ""
        return "GUS memory does not handle this action"


class GusMemoryOwner:
    """Authorize, execute and journal one explicit GUS memory operation."""

    def __init__(self, roots, approvals: ActionApprovalStore) -> None:
        self.roots = roots
        self.approvals = approvals
        store = GusMemoryStore(root=roots.settings.directory.parent)
        store.ensure()
        self.store = store
        self.root = store.directory.resolve(strict=True)
        self.authority = GusMemoryAuthority(
            self.root, consented=roots.settings.consented(roots.data),
            mode=str(roots.data.get("memory_mode") or EXPLICIT))
        self.gate = ProductActionGate(self.root, self.authority, owner_id=OWNER_ID,
                                      extra_systembilities=(GusMemoryBoundary(),))

    def write_requires_approval(self) -> bool:
        return self.authority.write_requires_approval()

    def prepare(self, operation: str, arguments: Any) -> MemoryPreview:
        args = _validate_arguments(operation, arguments)
        if operation == "remember":
            args["text"] = redact_memory(args["text"])
        return self._preview(operation, args)

    def _preview(self, operation: str, args: dict[str, Any]) -> MemoryPreview:
        encoded = _canonical_json(args)
        subject = str(args.get("id") or args.get("workspace") or operation)
        request = ActionRequest(OPERATION_ACTION[operation], self.root, subject, {
            "operation": operation,
            "arguments_sha256": _digest(encoded),
            "size": len(encoded.encode("utf-8")),
        }, execution_owner="gus_memory")
        return MemoryPreview(request, operation, args, text=str(args.get("text") or ""))

    def execute(self, preview: MemoryPreview,
                approval: ActionApproval | None = None) -> ActionOutcome:
        if not isinstance(preview, MemoryPreview):
            raise TypeError("GUS memory execution requires a prepared request")
        try:
            checked = self._preview(preview.operation,
                                    _validate_arguments(preview.operation, preview.arguments))
        except (TypeError, ValueError) as exc:
            return ActionOutcome("Memory operation denied.", "DENY", None, str(exc)[:200])
        if checked.request.digest != preview.request.digest:
            return ActionOutcome("Memory operation denied.", "DENY", None,
                                 "memory operation changed after review")
        _, decision = self.gate.authorize(preview.request, approvals=self.approvals,
                                          approval=approval)
        if not decision.allowed:
            return ActionOutcome("Memory operation denied.", "DENY", None,
                                 "; ".join(check.reason for check in decision.checks
                                           if not check.passed)[:300])
        try:
            if preview.operation == "remember":
                entry = self.store.add(preview.arguments["text"],
                                       workspace=preview.arguments["workspace"])
                result: dict[str, Any] = {"remembered": True, "id": entry["id"]}
            elif preview.operation == "forget":
                result = self.store.forget(preview.arguments["id"])
            else:
                result = {"cleared": self.store.clear()}
        except (GusMemoryError, OSError) as exc:
            return ActionOutcome("Memory operation failed.", "ERROR", None,
                                 f"{type(exc).__name__}: {str(exc)[:160]}")
        text = _canonical_json(result)
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), preview.request.action_id, preview.request.digest,
            "ALLOW", "SUCCESS", _digest(text),
        )
        if not receipt.verify(preview.request, text) or not self.gate.persist_receipt(
                preview.request, receipt):
            return ActionOutcome("Memory operation completed but could not be verified.",
                                 "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(text, "ALLOW", receipt,
                             f"GUS memory {preview.operation} completed")


def _validate_arguments(operation: str, arguments: Any) -> dict[str, Any]:
    if operation not in OPERATION_ACTION:
        raise GusMemoryError("GUS memory operation is unknown")
    if not isinstance(arguments, dict):
        raise GusMemoryError("memory arguments must be a JSON object")
    if len(_canonical_json(arguments).encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise GusMemoryError("memory arguments exceed 64 KiB")
    args = dict(arguments)
    if operation == "remember":
        if set(args) != {"text", "workspace"}:
            raise GusMemoryError("a memory needs text and its workspace")
        if not isinstance(args["text"], str) or not args["text"].strip():
            raise GusMemoryError("a memory needs text")
        if not isinstance(args["workspace"], str):
            raise GusMemoryError("a memory needs a workspace string")
        args["workspace"] = args["workspace"][:4096]
    elif operation == "forget":
        if set(args) != {"id"} or not isinstance(args["id"], str) \
                or not _IDENTIFIER.fullmatch(args["id"]):
            raise GusMemoryError("memory id is invalid")
    elif set(args):
        raise GusMemoryError("clearing GUS's memory takes no arguments")
    return args


__all__ = [
    "AUTOMATIC", "EXPLICIT", "FORGET_ACTION", "GusConversation", "GusMemoryAuthority",
    "GusMemoryBoundary", "GusMemoryError", "GusMemoryOwner", "GusMemoryStore",
    "MAX_CONVERSATION_CHARS", "MAX_CONVERSATION_ENTRIES", "MAX_MEMORIES",
    "MAX_MEMORIES_INJECTED", "MEMORY_ACTION", "MEMORY_MODES", "MemoryPreview",
    "OWNER_ID", "redact_memory", "memory_texts",
]
