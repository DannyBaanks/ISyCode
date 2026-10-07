"""M6A-S1: durable agent event store (G6A-06 contract/quota/redaction parts)."""
import json

import pytest

from isycode.agent_events import (
    EVENT_CONTRACT_VERSION, MAX_EVENTS_PER_RUN, AgentEventStore,
)

CANARY = "sk-canaryM6A0123456789abcdef"


def _store(tmp_path):
    return AgentEventStore("ws-test", directory=tmp_path / "events")


def test_contract_fields_and_monotonic_sequences(tmp_path):
    store = _store(tmp_path)
    first = store.append("task-1", "run-1", None, "start", "running", {"goal": "demo"})
    second = store.append("task-1", "run-1", None, "progress", "running", {"note": "half"})
    child = store.append("task-1", "run-2", "run-1", "start", "queued")
    for event in (first, second, child):
        data = event.to_dict()
        assert data["version"] == EVENT_CONTRACT_VERSION
        assert data["event_id"] and data["timestamp"] > 0
    assert (first.sequence, second.sequence) == (1, 2)
    assert child.sequence == 1 and child.parent_run_id == "run-1"


def test_canary_is_redacted_before_persistence(tmp_path):
    store = _store(tmp_path)
    store.append("task-1", "run-1", None, "error", "failed",
                 {"message": f"call failed with Bearer {CANARY}",
                  "detail": {"authorization": f"Bearer {CANARY}"},
                  "raw": CANARY})
    raw = store.path.read_text(encoding="utf-8")
    assert CANARY not in raw
    assert "Bearer [redacted]" in raw
    result = store.read()
    assert CANARY not in json.dumps([event.to_dict() for event in result.events])


def test_payload_is_bounded_and_validated(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.append("task-1", "run-1", None, "progress", "running",
                     {"blob": "x" * (64 * 1024)})
    with pytest.raises(ValueError):
        store.append("task-1", "run-1", None, "think", "running")
    with pytest.raises(ValueError):
        store.append("task-1", "run-1", None, "progress", "daydreaming")


def test_cursor_read_reports_gaps_duplicates_and_corruption(tmp_path):
    store = _store(tmp_path)
    store.append("task-1", "run-1", None, "start", "running")
    store.append("task-1", "run-1", None, "finish", "completed")
    lines = store.path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    lines.insert(1, json.dumps({**first, "sequence": 3}))  # duplicate id, odd order
    lines.append("not json at all")
    store.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = store.read()
    kinds = {gap["kind"] for gap in result.gaps}
    assert "duplicate" in kinds and "corrupt" in kinds
    assert result.degraded is True
    assert [event.sequence for event in result.events if event.run_id == "run-1"] == [1, 2]
    again = store.read(result.cursor)
    assert again.events == []


def test_restart_continues_sequences_and_keeps_events(tmp_path):
    store = _store(tmp_path)
    store.append("task-1", "run-1", None, "start", "running")
    store.append("task-1", "run-1", None, "progress", "running")
    reopened = AgentEventStore("ws-test", directory=tmp_path / "events")
    third = reopened.append("task-1", "run-1", None, "finish", "completed")
    assert third.sequence == 3
    assert len(reopened.read().events) == 3


def test_rotation_keeps_a_marker_and_both_generations(tmp_path, monkeypatch):
    monkeypatch.setattr("isycode.agent_events.MAX_FILE_BYTES", 2048)
    store = _store(tmp_path)
    for index in range(40):
        store.append("task-1", "run-1", None, "progress", "running",
                     {"note": f"line {index} " + "x" * 40})
    assert store.rotated_path.exists()
    assert "log.rotated" in store.path.read_text(encoding="utf-8")
    result = store.read(limit=1000)
    types = {event.type for event in result.events}
    assert "log.rotated" in types


def test_run_quota_drops_noise_but_never_terminal_states(tmp_path, monkeypatch):
    monkeypatch.setattr("isycode.agent_events.MAX_EVENTS_PER_RUN", 10)
    store = _store(tmp_path)
    store.append("task-1", "run-1", None, "start", "running")
    for index in range(9):
        store.append("task-1", "run-1", None, "progress", "running", {"i": index})
    with pytest.raises(ValueError, match="dropped"):
        store.append("task-1", "run-1", None, "progress", "running", {"i": 99})
    store.append("task-1", "run-1", None, "error", "failed", {"reason": "boom"})
    store.append("task-1", "run-1", None, "finish", "failed")
    states = [event.state for event in store.read(limit=100).events]
    assert "failed" in states
    assert any(event.type == "log.dropped" for event in store.read(limit=100).events)


def test_snapshot_returns_latest_per_run_for_reconnect(tmp_path):
    store = _store(tmp_path)
    store.append("task-1", "run-1", None, "start", "running")
    store.append("task-1", "run-2", "run-1", "start", "queued")
    store.append("task-1", "run-2", "run-1", "finish", "completed")
    snap = store.snapshot()
    assert snap["run-1"].state == "running"
    assert snap["run-2"].state == "completed"
    assert snap["run-2"].parent_run_id == "run-1"


def test_ten_thousand_events_slow_consumer_preserves_terminals(tmp_path):
    """G6A-06 scale check: quotas hold, terminal states and acks survive."""
    store = _store(tmp_path)
    store.append("task-1", "run-1", None, "start", "running")
    for index in range(10_000):
        try:
            store.append("task-1", "run-1", None, "progress", "running", {"i": index})
        except ValueError:
            pass
    store.append("task-1", "run-1", None, "error", "failed", {"reason": "late failure"})
    store.append("task-1", "run-1", None, "finish", "failed")
    states = [event.state for event in store.read(limit=10_000).events]
    assert "failed" in states
    assert any(event.type == "log.dropped" for event in store.read(limit=10_000).events)
    assert store.snapshot()["run-1"].state == "failed"
