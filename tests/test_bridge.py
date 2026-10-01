#!/usr/bin/env python3
"""M3 — Multi-agent via Bridge.

Gate: two agents collaborate on a task without collision, using
hello / claim / release / peek.

Bridge semantics (verified live): a lease with real disk activity in
its declared path is protected; an idle lease may be taken over.
The collaboration pattern is: claim -> work -> release -> handoff.
"""
from __future__ import annotations

import sys
import time
import uuid
import pathlib
import tempfile
import shutil
from pathlib import Path

import pytest

ISYCODE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ISYCODE_ROOT))

from isycode.bridge import BridgeClient, BridgeError

pytestmark = pytest.mark.integration


def test_two_agents_collaborate_without_collision():
    """A works under lease, B cannot steal it, B takes over after release."""
    topic = f"isycode-m3-{uuid.uuid4().hex[:8]}"
    workdir = Path(tempfile.mkdtemp(prefix="isycode-m3-"))
    a = BridgeClient(f"isycode-m3a-{uuid.uuid4().hex[:6]}")
    b = BridgeClient(f"isycode-m3b-{uuid.uuid4().hex[:6]}")
    try:
        a.hello()
        b.hello()

        # A claims and does REAL disk work in the declared path
        a.claim(topic, ttl=300, path=str(workdir))
        (workdir / "part1.txt").write_text("agent A work")
        time.sleep(0.5)

        # B tries to steal A's ACTIVE lease — must be denied
        try:
            b.claim(topic, ttl=60, path=str(workdir))
            stolen = True
        except BridgeError:
            stolen = False
        assert not stolen, "B must not steal A's active lease"

        # A finishes and releases
        a.send("maintainer", "PROGRESS", topic, "A done part 1")
        a.release(topic)

        # B takes over cleanly after release and does its part
        b.claim(topic, ttl=60, path=str(workdir))
        (workdir / "part2.txt").write_text("agent B work")
        b.send("maintainer", "PROGRESS", topic, "B done part 2")
        b.release(topic)

        # Both parts exist — no collision, no lost work
        assert (workdir / "part1.txt").read_text() == "agent A work"
        assert (workdir / "part2.txt").read_text() == "agent B work"
    finally:
        for agent in (a, b):
            try:
                agent.release(topic)
            except BridgeError:
                pass
        shutil.rmtree(workdir, ignore_errors=True)


def test_heartbeat_and_peek():
    """Agents can heartbeat and peek the mailbox."""
    a = BridgeClient(f"isycode-m3c-{uuid.uuid4().hex[:6]}")
    a.hello()
    a.heartbeat("m3-alive")
    peek = a.peek()
    assert isinstance(peek, list)
    assert all(isinstance(item, dict) for item in peek)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
