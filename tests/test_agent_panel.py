"""M6A-S3: sidebar run tree (G6A-01) and distinct queue actions (G6A-04 parts)."""
import pytest

from isycode.agent_events import AgentEventStore
from isycode.agent_panel import AgentPanelModel
from isycode.instruction_queue import InstructionQueue


def _store(tmp_path):
    return AgentEventStore("ws-test", directory=tmp_path / "events")


def _fill_run(store, run_id, parent, count, *, final="completed"):
    store.append("task-1", run_id, parent, "start", "running",
                 {"goal": f"goal of {run_id}"})
    for index in range(count - 2):
        store.append("task-1", run_id, parent, "progress", "running", {"i": index})
    store.append("task-1", run_id, parent, "finish", final)


def test_eight_agents_one_hundred_events_each_never_mix(tmp_path):
    store = _store(tmp_path)
    _fill_run(store, "run-root", None, 100)
    for index in range(7):
        _fill_run(store, f"run-{index}", "run-root", 100, final="running" if index % 2 else "failed")
    panel = AgentPanelModel(store)
    assert len(panel.runs) == 8
    roots = panel.tree()
    assert [root.run_id for root in roots] == ["run-root"]
    root = roots[0]
    assert len(root.children) == 7
    assert all(child.parent_run_id == "run-root" for child in root.children)
    assert all(node.event_count == 100 for node in panel.runs.values())
    counts = panel.counts_by_state()
    assert counts == {"completed": 1, "running": 3, "failed": 4}
    for node in panel.runs.values():
        assert node.goal == f"goal of {node.run_id}"
        detail = panel.detail(node.run_id, limit=5)
        assert len(detail) == 5
        assert all(event.run_id == node.run_id for event in detail)


def test_incremental_refresh_keeps_cursor_and_folds_deltas(tmp_path):
    store = _store(tmp_path)
    store.append("task-1", "run-1", None, "start", "running")
    panel = AgentPanelModel(store)
    assert panel.runs["run-1"].state == "running"
    assert panel.refresh() == 0
    store.append("task-1", "run-1", None, "wait", "waiting-input", {"reason": "question"})
    store.append("task-1", "run-1", None, "finish", "completed")
    assert panel.refresh() == 2
    assert panel.runs["run-1"].state == "completed"
    assert panel.runs["run-1"].last_type == "finish"


def test_distinct_actions_have_distinct_effects(tmp_path):
    store = _store(tmp_path)
    store.append("task-1", "run-1", None, "start", "running")
    queue = InstructionQueue("ws-test", directory=tmp_path / "queue")
    next_turn = queue.submit("task-1", "run-1", "next_turn", "after this, also run lint")
    correction = queue.submit("task-1", "run-1", "correct", "use the small model instead")
    stop = queue.submit("task-1", "run-1", "cancel", "stop everything now")
    assert next_turn.intent == "next_turn" and queue.pending("run-1")[0].intent == "next_turn"
    queue.mark_received(correction.message_id)
    applied = queue.apply(correction.message_id, boundary="before-next-model-call")
    assert applied.ack == "applied" and applied.boundary == "before-next-model-call"
    queue.mark_received(stop.message_id)
    stopped = queue.apply(stop.message_id, boundary="immediate")
    assert stopped.ack == "applied" and stopped.boundary == "immediate"
    store.append("task-1", "run-1", None, "finish", "cancelled",
                 {"by": stop.message_id})
    panel = AgentPanelModel(store)
    assert panel.runs["run-1"].state == "cancelled"
    assert [item.intent for item in queue.pending("run-1")] == ["next_turn"]


def test_unknown_run_detail_is_empty_and_states_are_distinct(tmp_path):
    store = _store(tmp_path)
    _fill_run(store, "run-a", None, 5, final="completed")
    _fill_run(store, "run-b", None, 5, final="failed")
    panel = AgentPanelModel(store)
    assert panel.detail("run-missing") == []
    assert panel.runs["run-a"].state != panel.runs["run-b"].state
