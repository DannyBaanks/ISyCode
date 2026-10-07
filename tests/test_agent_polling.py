"""M6A-S4: polling fallback and latency budgets (G6A-07/08)."""
import statistics
import time

from isycode.agent_events import AgentEventStore
from isycode.agent_polling import PollingCursor
from isycode.instruction_queue import InstructionQueue


def _store(tmp_path):
    return AgentEventStore("ws-test", directory=tmp_path / "events")


def test_polling_respects_interval_and_visible_backoff(tmp_path):
    store = _store(tmp_path)
    cursor = PollingCursor(store, interval_s=1.0, backoff_factor=2.0, max_interval_s=4.0)
    cursor.poll_once()
    assert cursor.effective_interval() == 2.0
    cursor.poll_once()
    assert cursor.effective_interval() == 4.0
    cursor.poll_once()
    assert cursor.effective_interval() == 4.0
    assert cursor.report.last_interval == 4.0
    store.append("task-1", "run-1", None, "start", "running")
    assert cursor.poll_once() == 1
    assert cursor.effective_interval() == 1.0


def test_reconnect_rebuilds_and_reports(tmp_path):
    store = _store(tmp_path)
    cursor = PollingCursor(store, interval_s=2.0)
    store.append("task-1", "run-1", None, "start", "running")
    assert cursor.reconnect() == 1
    assert cursor.report.reconnects == 1
    store.append("task-1", "run-1", None, "finish", "completed")
    assert cursor.reconnect() == 1
    assert cursor.report.events == 2
    assert cursor.age_s(now=cursor.clock() + 5) >= 0


def test_g6a07_event_display_and_ack_latency_p95(tmp_path):
    """100 samples each: append->visible and submit->received, p95 <= 1s locally."""
    store = _store(tmp_path)
    queue = InstructionQueue("ws-test", directory=tmp_path / "queue")
    display_samples = []
    ack_samples = []
    cursor = PollingCursor(store, interval_s=1.0)
    for index in range(100):
        started = time.perf_counter()
        store.append("task-1", "run-1", None, "progress", "running", {"i": index})
        cursor.poll_once()
        display_samples.append(time.perf_counter() - started)
        started = time.perf_counter()
        item = queue.submit("task-1", "run-1", "correct", f"note {index}")
        queue.mark_received(item.message_id)
        ack_samples.append(time.perf_counter() - started)
    display_p95 = statistics.quantiles(display_samples, n=20)[18]
    ack_p95 = statistics.quantiles(ack_samples, n=20)[18]
    assert display_p95 <= 1.0, f"display p95 {display_p95:.3f}s over budget"
    assert ack_p95 <= 1.0, f"ack p95 {ack_p95:.3f}s over budget"
