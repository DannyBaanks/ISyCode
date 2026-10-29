"""M6A-S2: instruction queue with public acks (G6A-02/03/05 parts)."""
import json

import pytest

from isycode.instruction_queue import InstructionQueue

CANARY = "sk-queueCanary0123456789abcdef"


def _queue(tmp_path, **kwargs):
    return InstructionQueue("ws-test", directory=tmp_path / "queue", **kwargs)


def test_submit_persists_sanitized_with_queued_ack(tmp_path):
    queue = _queue(tmp_path)
    item = queue.submit("task-1", "run-1", "correct", f"please use Bearer {CANARY} carefully")
    assert item.ack == "queued"
    assert CANARY not in queue.path.read_text(encoding="utf-8")
    assert queue.get(item.message_id).content != f"please use Bearer {CANARY} carefully"


def test_three_intents_are_distinct(tmp_path):
    queue = _queue(tmp_path)
    intents = [queue.submit("task-1", "run-1", intent, f"do {intent}")
               for intent in ("next_turn", "correct", "cancel")]
    assert [item.intent for item in intents] == ["next_turn", "correct", "cancel"]
    assert [item.sequence for item in intents] == [1, 2, 3]
    with pytest.raises(ValueError):
        queue.submit("task-1", "run-1", "merge_args", "nope")


def test_ack_lifecycle_and_idempotent_reapply(tmp_path):
    queue = _queue(tmp_path)
    item = queue.submit("task-1", "run-1", "correct", "switch to the small model")
    queue.mark_received(item.message_id)
    applied = queue.apply(item.message_id, boundary="before-next-model-call")
    assert applied.ack == "applied" and applied.boundary == "before-next-model-call"
    again = queue.apply(item.message_id, boundary="before-next-model-call")
    assert again.timestamp == applied.timestamp


def test_restart_replays_without_double_apply(tmp_path):
    queue = _queue(tmp_path)
    item = queue.submit("task-1", "run-1", "correct", "narrow the scope")
    queue.mark_received(item.message_id)
    queue.apply(item.message_id, boundary="tool-end")
    reopened = InstructionQueue("ws-test", directory=tmp_path / "queue")
    replayed = reopened.get(item.message_id)
    assert replayed.ack == "applied" and replayed.boundary == "tool-end"
    assert reopened.apply(item.message_id, boundary="tool-end").timestamp == replayed.timestamp
    assert len(queue.path.read_text(encoding="utf-8").splitlines()) == 3


def test_crash_between_received_and_applied_is_redriven(tmp_path):
    queue = _queue(tmp_path)
    item = queue.submit("task-1", "run-1", "cancel", "stop now")
    queue.mark_received(item.message_id)
    reopened = InstructionQueue("ws-test", directory=tmp_path / "queue")
    pending = reopened.pending("run-1")
    assert [msg.message_id for msg in pending] == [item.message_id]
    applied = reopened.apply(item.message_id, boundary="immediate")
    assert applied.ack == "applied"


def test_revocation_while_queued_blocks_the_effect(tmp_path):
    queue = _queue(tmp_path)
    item = queue.submit("task-1", "run-1", "correct", "delete the scratch dir")
    allowed = {"state": True}

    def authority_check(instruction):
        return (allowed["state"], "" if allowed["state"] else "grant revoked while queued")

    queue.mark_received(item.message_id)
    allowed["state"] = False
    rejected = queue.apply(item.message_id, boundary="tool-end",
                           authority_check=authority_check)
    assert rejected.ack == "rejected"
    assert "revoked" in rejected.ack_reason


def test_closed_run_rejects_and_never_migrates_silently(tmp_path):
    closed = {"run-1"}
    queue = _queue(tmp_path, run_closed=lambda run_id: run_id in closed)
    with pytest.raises(ValueError, match="closed"):
        queue.submit("task-1", "run-1", "correct", "too late")
    queue2 = _queue(tmp_path, run_closed=lambda run_id: run_id in closed)
    item = queue2.submit("task-1", "run-2", "correct", "in time")
    closed.add("run-2")
    rejected = queue2.apply(item.message_id, boundary="tool-end")
    assert rejected.ack == "rejected" and "closed" in rejected.ack_reason
    assert queue2.get(item.message_id).run_id == "run-2"


def test_rejected_keeps_reason_and_ignores_later_acks(tmp_path):
    queue = _queue(tmp_path)
    item = queue.submit("task-1", "run-1", "correct", "skip the tests")
    queue.reject(item.message_id, "user chose otherwise")
    assert queue.get(item.message_id).ack_reason == "user chose otherwise"
    assert queue.apply(item.message_id, boundary="tool-end").ack == "rejected"
