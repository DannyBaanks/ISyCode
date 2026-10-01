#!/usr/bin/env python3
"""M2.5 — Resumable sessions / provider handoff tests.

Gate: provider dies after step 2/4 -> replacement model continues from
step 3, no successful write is replayed, receipt chain stays intact.
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

ISYCODE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ISYCODE_ROOT))

from isycode.session import (
    SessionState, SessionStore, ExecutedStepRecord,
    new_session, record_step, handoff, verify_chain,
)


def make_store() -> tuple[SessionStore, Path]:
    d = Path(tempfile.mkdtemp(prefix="isycode-m25-"))
    return SessionStore(str(d)), d


FOUR_STEPS = [
    {"host": "win98-retrobox", "capability": "filesystem.read",
     "params": {"path": "hostfs://games"}, "why": "List GAMES"},
    {"host": "win98-retrobox", "capability": "filesystem.read",
     "params": {"path": "hostfs://games/DOOM.EXE"}, "why": "Read newest"},
    {"host": "win98-retrobox", "capability": "filesystem.write",
     "params": {"path": "hostfs://inbox/DOOM.EXE"}, "why": "Write to inbox"},
    {"host": "win98-retrobox", "capability": "apps.launch",
     "params": {"app": "doom"}, "why": "Launch DOOM"},
]


def test_handoff_after_step_2_of_4():
    """Provider dies after step 2/4 -> replacement continues from step 3."""
    store, tmp = make_store()
    try:
        # Original provider starts the session, executes steps 0-1
        s = new_session("copy and launch", "plan-abc", FOUR_STEPS,
                        ["filesystem.read", "filesystem.write", "apps.launch"],
                        provider="nvidia")
        record_step(s, 0, "win98-retrobox", "filesystem.read",
                    {"path": "hostfs://games"}, "rcpt-0", "digest-0", "ALLOW")
        record_step(s, 1, "win98-retrobox", "filesystem.read",
                    {"path": "hostfs://games/DOOM.EXE"}, "rcpt-1", "digest-1", "ALLOW")
        store.save(s)

        # Provider dies. New provider loads durable state.
        s2 = store.load(s.session_id)
        assert s2.next_index == 2, "must resume from step 3 (index 2)"
        assert len(s2.outstanding) == 2
        assert not s2.is_complete()

        # Handoff to replacement provider
        handoff(s2, "nebius")

        # Replacement executes remaining steps — never replays 0-1
        executed_indices = []
        for idx in range(s2.next_index, len(s2.steps)):
            step = s2.steps[idx]
            executed_indices.append(idx)
            record_step(s2, idx, step["host"], step["capability"],
                        step["params"], f"rcpt-{idx}", f"digest-{idx}", "ALLOW")
        store.save(s2)

        assert executed_indices == [2, 3], "only steps 2-3 execute, never 0-1"
        assert s2.is_complete()

        # Receipt chain intact: prefix 0..3, no gaps, all digests present
        ok, msg = verify_chain(s2)
        assert ok, msg
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_duplicate_execution_on_recovery():
    """A step with a receipt is never replayed after recovery."""
    store, tmp = make_store()
    try:
        s = new_session("x", "p1", FOUR_STEPS[:2], ["filesystem.read"], "nvidia")
        record_step(s, 0, "h", "filesystem.read", {}, "r0", "d0", "ALLOW")
        # Duplicate record attempt — must be a no-op
        record_step(s, 0, "h", "filesystem.read", {}, "r0-dup", "d0-dup", "ALLOW")
        assert len(s.executed) == 1, "duplicate record must be a no-op"
        assert s.executed[0].receipt_digest == "d0", "original receipt kept"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_receipt_chain_detects_gaps():
    """verify_chain fails on a gapped chain."""
    store, tmp = make_store()
    try:
        s = new_session("x", "p1", FOUR_STEPS, ["filesystem.read"], "nvidia")
        record_step(s, 0, "h", "filesystem.read", {}, "r0", "d0", "ALLOW")
        record_step(s, 2, "h", "filesystem.write", {}, "r2", "d2", "ALLOW")
        ok, msg = verify_chain(s)
        assert not ok, "gapped chain must fail verification"
        assert "gaps" in msg
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_session_survives_provider_change():
    """Session identity, plan, and approvals survive handoff."""
    store, tmp = make_store()
    try:
        s = new_session("copy and launch", "plan-xyz", FOUR_STEPS,
                        ["filesystem.read", "filesystem.write"],
                        provider="nvidia", lease_id="lease-1")
        s.approvals.append("seal-abc")
        store.save(s)

        s2 = store.load(s.session_id)
        handoff(s2, "ollama")

        assert s2.session_id == s.session_id
        assert s2.intent == s.intent
        assert s2.plan_id == s.plan_id
        assert s2.steps == s.steps
        assert s2.approvals == ["seal-abc"]
        assert s2.lease_id == "lease-1"
        assert s2.provider == "ollama"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_empty_session_has_no_next_step_gaps():
    """Fresh session: next_index=0, outstanding=all, not complete."""
    s = new_session("x", "p1", FOUR_STEPS, ["filesystem.read"], "nvidia")
    assert s.next_index == 0
    assert len(s.outstanding) == 4
    assert not s.is_complete()
    ok, _ = verify_chain(s)
    assert ok


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
