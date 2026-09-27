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
import hashlib
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any
from pathlib import Path


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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        return cls(
            session_id=d["session_id"],
            intent=d["intent"],
            plan_id=d["plan_id"],
            steps=d["steps"],
            executed=[ExecutedStepRecord(**e) for e in d["executed"]],
            capabilities=d["capabilities"],
            approvals=d["approvals"],
            lease_id=d.get("lease_id"),
            provider=d["provider"],
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
        )


class SessionStore:
    """Persists session state to disk. Atomic writes."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or os.path.expanduser("~/.isycode/sessions"))
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        # Sanitize: session IDs are hex, no path traversal
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self.root / f"{safe}.json"

    def save(self, state: SessionState) -> Path:
        state.updated_at = time.time()
        p = self._path(state.session_id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=1, default=str))
        tmp.rename(p)
        return p

    def load(self, session_id: str) -> SessionState:
        p = self._path(session_id)
        if not p.exists():
            raise FileNotFoundError(f"no such session: {session_id}")
        return SessionState.from_dict(json.loads(p.read_text()))

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()


def new_session(intent: str, plan_id: str, steps: list[dict],
                capabilities: list[str], provider: str,
                lease_id: str | None = None) -> SessionState:
    """Create a fresh session for an accepted plan."""
    now = time.time()
    return SessionState(
        session_id=uuid.uuid4().hex[:16],
        intent=intent, plan_id=plan_id, steps=steps,
        executed=[], capabilities=list(capabilities), approvals=[],
        lease_id=lease_id, provider=provider,
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
    0..k with no gaps, and each has a non-empty receipt digest."""
    indices = sorted(e.index for e in state.executed)
    if not indices:
        return True, "empty chain (nothing executed yet)"
    expected = list(range(len(indices)))
    if indices != expected:
        return False, f"chain has gaps: {indices} != {expected}"
    for e in state.executed:
        if not e.receipt_digest:
            return False, f"step {e.index} missing receipt digest"
    return True, f"chain intact: {len(indices)} receipts"
