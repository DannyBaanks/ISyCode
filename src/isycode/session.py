#!/usr/bin/env python3
"""ISyCode Resumable Sessions — durable agent state for provider handoff.

If a provider dies mid-plan (429, timeout, outage, process death), a
replacement model resumes from verifiable durable state — WITHOUT
pretending private memory of the first model.

Durable state (NOT only in model context):
- session identity
- current intent
- accepted plan (plan_id + steps)
- executed steps (with receipts)
- outstanding steps
- capabilities snapshot
- approvals
- lease

Idempotency: a step that already produced a receipt is NEVER replayed.
The receipt chain is the source of truth, not the model.
"""
from __future__ import annotations

import os
import json
import time
import re
import stat
import tempfile
import uuid
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable


class SessionIntegrityError(ValueError):
    """A persisted session is malformed or its execution record chain is invalid."""


class SessionAuthorityChanged(SessionIntegrityError):
    """Current host authority does not match the session snapshot."""


@dataclass
class ExecutedStepRecord:
    """One completed step with its receipt."""
    index: int
    host: str
    capability: str
    params: dict
    receipt_id: str
    receipt_digest: str
    decision: str  # ALLOW or DENY
    timestamp: float = 0.0


@dataclass
class SessionState:
    """Durable session state — everything needed to resume."""
    session_id: str
    intent: str
    plan_id: str
    steps: list[dict]  # accepted plan steps (host, capability, params, why)
    executed: list[ExecutedStepRecord]
    capabilities: list[str]  # granted capability snapshot
    approvals: list[str]  # approved manifest seals
    lease_id: str | None
    provider: str  # provider name that started the session
    authority_fingerprint: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def outstanding(self) -> list[dict]:
        """Steps not yet executed (by index)."""
        done = {e.index for e in self.executed}
        return [s for i, s in enumerate(self.steps) if i not in done]

    @property
    def next_index(self) -> int | None:
        """Index of the next step to execute, or None if done."""
        done = {e.index for e in self.executed}
        for i in range(len(self.steps)):
            if i not in done:
                return i
        return None

    def is_complete(self) -> bool:
        return self.next_index is None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "intent": self.intent,
            "plan_id": self.plan_id,
            "steps": self.steps,
            "executed": [asdict(e) for e in self.executed],
            "capabilities": self.capabilities,
            "approvals": self.approvals,
            "lease_id": self.lease_id,
            "provider": self.provider,
            "authority_fingerprint": self.authority_fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        if not isinstance(d, dict):
            raise SessionIntegrityError("session payload must be an object")
        for field in ("session_id", "intent", "plan_id", "provider"):
            if not isinstance(d.get(field), str):
                raise SessionIntegrityError(f"session field {field} must be text")
        if not isinstance(d.get("steps"), list) or not all(
                isinstance(item, dict) for item in d["steps"]):
            raise SessionIntegrityError("session steps must be a list of objects")
        if not isinstance(d.get("executed"), list) or not all(
                isinstance(item, dict) for item in d["executed"]):
            raise SessionIntegrityError("session executed records must be a list of objects")
        if not isinstance(d.get("capabilities"), list) or not all(
                isinstance(item, str) for item in d["capabilities"]):
            raise SessionIntegrityError("session capabilities must be a list of strings")
        if not isinstance(d.get("approvals"), list) or not all(
                isinstance(item, str) for item in d["approvals"]):
            raise SessionIntegrityError("session approvals must be a list of strings")
        if d.get("lease_id") is not None and not isinstance(d.get("lease_id"), str):
            raise SessionIntegrityError("session lease_id must be text or null")
        fingerprint = d.get("authority_fingerprint")
        if fingerprint is not None and not isinstance(fingerprint, str):
            raise SessionIntegrityError("authority_fingerprint must be text or null")
        for field in ("created_at", "updated_at"):
            value = d.get(field, 0.0)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise SessionIntegrityError(f"session field {field} must be a finite timestamp")
        steps = d["steps"]
        for index, step in enumerate(steps):
            if (not isinstance(step.get("host"), str)
                    or not isinstance(step.get("capability"), str)
                    or not isinstance(step.get("params"), dict)):
                raise SessionIntegrityError(f"plan step {index} is malformed")
        try:
            executed = [ExecutedStepRecord(**item) for item in d["executed"]]
        except (TypeError, KeyError) as exc:
            raise SessionIntegrityError("executed record is malformed") from exc
        for record in executed:
            if (not isinstance(record.index, int) or isinstance(record.index, bool)
                    or not isinstance(record.host, str)
                    or not isinstance(record.capability, str)
                    or not isinstance(record.params, dict)
                    or not isinstance(record.receipt_id, str)
                    or not isinstance(record.receipt_digest, str)
                    or not isinstance(record.decision, str)
                    or record.decision not in {"ALLOW", "DENY"}
                    or not isinstance(record.timestamp, (int, float))
                    or isinstance(record.timestamp, bool)
                    or not math.isfinite(record.timestamp)):
                raise SessionIntegrityError("executed record contains invalid fields")
        return cls(
            session_id=d["session_id"],
            intent=d["intent"],
            plan_id=d["plan_id"],
            steps=steps,
            executed=executed,
            capabilities=d["capabilities"],
            approvals=d["approvals"],
            lease_id=d.get("lease_id"),
            provider=d["provider"],
            authority_fingerprint=fingerprint,
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
        )


@dataclass(frozen=True)
class SessionInspection:
    """Parsed session data plus structural chain status; never grants resume authority."""

    state: SessionState
    chain_valid: bool
    chain_reason: str


class SessionStore:
    """Persists session state privately with atomic replacement."""

    _SESSION_ID = re.compile(r"^[a-f0-9]{16}$")
    MAX_SESSION_BYTES = 4_000_000

    def __init__(self, root: str | None = None):
        self.root = Path(root or os.path.expanduser("~/.isycode/sessions"))
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("session store root must be a real directory, not a symlink")
        self.root = self.root.resolve(strict=True)
        if os.name == "posix":
            self.root.chmod(0o700)

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not self._SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid session id")
        return self.root / f"{session_id}.json"

    def save(self, state: SessionState) -> Path:
        state.updated_at = time.time()
        p = self._path(state.session_id)
        payload = json.dumps(
            state.to_dict(), indent=1, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > self.MAX_SESSION_BYTES:
            raise ValueError("session state exceeds the 4 MB storage limit")
        fd, temporary = tempfile.mkstemp(
            prefix=f".{state.session_id}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, p)
            if os.name == "posix":
                directory_fd = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return p

    def load(self, session_id: str) -> SessionState:
        """Load only a structurally intact chain; legacy approval fields are not authority."""
        inspection = self.load_for_inspection(session_id)
        if not inspection.chain_valid:
            raise SessionIntegrityError(inspection.chain_reason)
        return inspection.state

    def load_for_inspection(self, session_id: str) -> SessionInspection:
        """Parse even a gapped chain for inspection without authorizing its resume."""
        p = self._path(session_id)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            fd = os.open(p, flags)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"no such session: {session_id}") from exc
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise SessionIntegrityError("session state is not a regular file")
            if info.st_size > self.MAX_SESSION_BYTES:
                raise SessionIntegrityError("session state exceeds the 4 MB load limit")
            try:
                raw = stream.read(self.MAX_SESSION_BYTES + 1)
                if len(raw.encode("utf-8")) > self.MAX_SESSION_BYTES:
                    raise SessionIntegrityError("session state exceeds the 4 MB load limit")
                state = SessionState.from_dict(json.loads(raw))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise SessionIntegrityError("session state is not valid UTF-8 JSON") from exc
        if state.session_id != session_id:
            raise SessionIntegrityError("session id does not match its state file")
        chain_valid, chain_reason = verify_chain(state)
        return SessionInspection(state, chain_valid, chain_reason)

    def load_for_resume(
        self,
        session_id: str,
        *,
        current_authority_fingerprint: str,
        verify_receipt: Callable[[ExecutedStepRecord], bool] | None = None,
    ) -> SessionState:
        """Load for resume only after authority and every executed receipt are rechecked."""
        inspection = self.load_for_inspection(session_id)
        if not inspection.chain_valid:
            raise SessionIntegrityError(inspection.chain_reason)
        state = inspection.state
        if (not state.authority_fingerprint
                or state.authority_fingerprint != current_authority_fingerprint):
            raise SessionAuthorityChanged(
                "current IsyMotron authority does not match the saved session")
        if state.executed and verify_receipt is None:
            raise SessionIntegrityError(
                "executed steps require current IsyMotron receipt verification before resume")
        for record in state.executed:
            try:
                verified = bool(verify_receipt(record)) if verify_receipt else False
            except Exception as exc:
                raise SessionIntegrityError(
                    f"receipt verification failed for step {record.index} ({type(exc).__name__})") from exc
            if not verified:
                raise SessionIntegrityError(
                    f"receipt verification rejected step {record.index}")
        # Approval seals and lease IDs are inspection data only after restart.
        # The caller must obtain a new contextual approval and lease.
        state.approvals.clear()
        state.lease_id = None
        state.updated_at = time.time()
        return state

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()


def new_session(intent: str, plan_id: str, steps: list[dict],
                capabilities: list[str], provider: str,
                lease_id: str | None = None,
                authority_fingerprint: str | None = None) -> SessionState:
    """Create a fresh session for an accepted plan."""
    now = time.time()
    return SessionState(
        session_id=uuid.uuid4().hex[:16],
        intent=intent, plan_id=plan_id, steps=steps,
        executed=[], capabilities=list(capabilities), approvals=[],
        lease_id=lease_id, provider=provider,
        authority_fingerprint=authority_fingerprint,
        created_at=now, updated_at=now,
    )


def record_step(state: SessionState, index: int, host: str, capability: str,
                params: dict, receipt_id: str, receipt_digest: str,
                decision: str) -> None:
    """Record an executed step. Idempotent: same index twice is a no-op."""
    if any(e.index == index for e in state.executed):
        return  # already recorded — never duplicate
    state.executed.append(ExecutedStepRecord(
        index=index, host=host, capability=capability, params=params,
        receipt_id=receipt_id, receipt_digest=receipt_digest,
        decision=decision, timestamp=time.time(),
    ))
    state.updated_at = time.time()


def handoff(state: SessionState, new_provider: str) -> SessionState:
    """Hand off a session to a replacement provider.

    The new provider gets the durable state — intent, plan, executed
    steps with receipts, outstanding steps — but NOT the old model's
    private context. It resumes from `next_index`, never replays.
    """
    state.provider = new_provider
    state.updated_at = time.time()
    return state


def verify_chain(state: SessionState) -> tuple[bool, str]:
    """Verify the receipt chain is intact: executed indices are a prefix
    0..k with no gaps, unique indices, matching plan steps and receipt refs."""
    indices = [e.index for e in state.executed]
    if not indices:
        return True, "empty chain (nothing executed yet)"
    if any(not isinstance(i, int) or isinstance(i, bool) for i in indices):
        return False, "chain contains a non-integer step index"
    ordered = sorted(indices)
    expected = list(range(len(ordered)))
    if ordered != expected:
        return False, f"chain has gaps or duplicate indices: {ordered} != {expected}"
    if len(ordered) > len(state.steps):
        return False, "chain contains indices beyond the accepted plan"
    for e in state.executed:
        if not (e.receipt_id and e.receipt_digest):
            return False, f"step {e.index} missing receipt id or digest"
        planned = state.steps[e.index]
        if (e.host != planned.get("host")
                or e.capability != planned.get("capability")
                or e.params != planned.get("params")):
            return False, f"step {e.index} does not match the accepted plan"
    return True, f"chain intact: {len(indices)} receipts"
