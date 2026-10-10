from __future__ import annotations

import threading
import time
from dataclasses import FrozenInstanceError
from concurrent.futures import ThreadPoolExecutor

import pytest

from isycode.dataflow import (
    DataflowChunk,
    DataflowChunkResult,
    DataflowExecutionError,
    map_ordered,
    split_accessibility_snapshot,
)


def _square(value: int) -> int:
    return value * value


class _CountingThreadPool(ThreadPoolExecutor):
    def __init__(self, max_workers: int):
        super().__init__(max_workers=max_workers)
        self.outstanding = 0
        self.max_outstanding = 0
        self._counter_lock = threading.Lock()

    def submit(self, *args, **kwargs):
        with self._counter_lock:
            self.outstanding += 1
            self.max_outstanding = max(self.max_outstanding, self.outstanding)
        future = super().submit(*args, **kwargs)

        def completed(_future):
            with self._counter_lock:
                self.outstanding -= 1

        future.add_done_callback(completed)
        return future


def test_split_chunks_are_indexed_and_reconstruct_exact_source() -> None:
    snapshot = (
        "- main [active]\n"
        "  - heading: Title\n"
        "  - paragraph: Alpha\n"
        "  - paragraph: Bravo\n"
        "  - paragraph: Charlie\n"
    )

    chunks = split_accessibility_snapshot(snapshot, target_chars=32)

    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert "".join(chunk.text for chunk in chunks) == snapshot
    assert all(len(chunk.text) <= 32 for chunk in chunks)


def test_split_carries_ancestor_and_skipped_subtree_context() -> None:
    snapshot = (
        "- main [active]\n"
        "  - navigation:\n"
        "    - link: Noise one\n"
        "    - link: Noise two\n"
        "  - paragraph: Useful\n"
    )

    chunks = split_accessibility_snapshot(snapshot, target_chars=37)

    skipped_chunk = next(chunk for chunk in chunks if "Noise two" in chunk.text)
    useful_chunk = next(chunk for chunk in chunks if "Useful" in chunk.text)
    assert skipped_chunk.ancestor_indents == (0, 2)
    assert skipped_chunk.ancestor_roles == ("main", "navigation")
    assert skipped_chunk.starts_inside_skipped_subtree is True
    assert useful_chunk.starts_inside_skipped_subtree is False


def test_split_preserves_legacy_single_skip_depth_when_skip_roles_nest() -> None:
    snapshot = (
        "- contentinfo:\n"
        "  - navigation:\n"
        "    - link: nested content\n"
        "  - paragraph: sibling content\n"
    )

    chunks = split_accessibility_snapshot(snapshot, target_chars=32)

    nested = next(chunk for chunk in chunks if "nested content" in chunk.text)
    assert nested.starts_inside_skipped_subtree is True
    # The current serial filter carries one active skip depth, not a stack of
    # skip depths. Preserve its observable behavior for serial equivalence.
    assert nested.skipped_ancestor_indent == 0


def test_single_oversized_line_is_kept_as_its_own_chunk() -> None:
    giant = "  - paragraph: " + ("x" * 100)
    snapshot = "- main [active]\n" + giant + "\n- footer: end\n"

    chunks = split_accessibility_snapshot(snapshot, target_chars=24)

    assert "".join(chunk.text for chunk in chunks) == snapshot
    assert [chunk.text for chunk in chunks if len(chunk.text) > 24] == [giant + "\n"]


def test_chunk_and_result_are_frozen_and_result_has_one_outcome() -> None:
    chunk = DataflowChunk(
        index=0,
        text="- paragraph: hi\n",
        ancestor_indents=(),
        ancestor_roles=(),
        starts_inside_skipped_subtree=False,
    )
    result = DataflowChunkResult(index=0, value="hi", error=None)

    with pytest.raises(FrozenInstanceError):
        chunk.index = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.index = 2  # type: ignore[misc]
    with pytest.raises(ValueError):
        DataflowChunkResult(index=0, value=None, error=None)
    with pytest.raises(ValueError):
        DataflowChunkResult(index=0, value="ok", error="bad")


def test_split_empty_malformed_unicode_and_oversized_node_are_deterministic() -> None:
    assert split_accessibility_snapshot("", target_chars=10) == []

    snapshot = "not a node\n- main [active]\n  - paragraph: café 🐈\n"
    chunks = split_accessibility_snapshot(snapshot, target_chars=20)
    assert "".join(chunk.text for chunk in chunks) == snapshot
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))

    with pytest.raises(ValueError, match="target_chars"):
        split_accessibility_snapshot(snapshot, target_chars=0)


def test_unicode_canary_and_adversarial_sidebar_survive_chunk_boundaries() -> None:
    from isycode.browser_read import (
        filter_accessibility_snapshot,
        filter_accessibility_snapshot_chunked,
    )

    snapshot = (
        "- generic:\n"
        '  - complementary:\n    - heading "API reference 🧠" [level=2]\n'
        "    - paragraph: Retry-After accepts seconds.\n"
        "  - main:\n    - button \"Subscribe to alerts\":\n"
        "    - paragraph: Useful text remains after the noisy control.\n"
    )
    legacy = filter_accessibility_snapshot(snapshot)
    chunked = filter_accessibility_snapshot_chunked(
        snapshot, target_chunk_chars=31, executor="serial"
    )

    assert "API reference 🧠" in legacy["content"]
    assert chunked["content"] == legacy["content"]
    assert "Subscribe to alerts" not in chunked["content"]
    assert "Useful text remains" in chunked["content"]


def test_map_ordered_returns_input_order_after_out_of_order_completion() -> None:
    completed: list[int] = []
    lock = threading.Lock()

    def staggered(value: int) -> int:
        time.sleep((3 - value) * 0.02)
        with lock:
            completed.append(value)
        return value * 10

    result = map_ordered(range(4), staggered, workers=4, executor="thread")

    assert result == [0, 10, 20, 30]
    assert completed != [0, 1, 2, 3]


def test_map_ordered_bounds_submissions_and_preserves_external_pool() -> None:
    pool = _CountingThreadPool(max_workers=2)
    try:
        result = map_ordered(range(20), _square, workers=2, executor="thread", pool=pool)
        assert result == [value * value for value in range(20)]
        assert pool.max_outstanding <= 2
        assert map_ordered([4], _square, workers=2, executor="thread", pool=pool) == [16]
    finally:
        pool.shutdown()


@pytest.mark.parametrize("executor", ["serial", "thread", "process"])
def test_map_ordered_executor_modes_are_equivalent(executor: str) -> None:
    assert map_ordered(range(8), _square, workers=2, executor=executor) == [
        value * value for value in range(8)
    ]


def test_map_ordered_rejects_invalid_worker_counts_and_pool_types() -> None:
    with pytest.raises(ValueError, match="workers"):
        map_ordered([1], _square, workers=0, executor="thread")
    with pytest.raises(ValueError, match="timeout"):
        map_ordered([1], _square, workers=1, executor="serial", timeout_s=0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(TypeError, match="executor"):
            map_ordered([1], _square, workers=1, executor="process", pool=pool)


def test_map_ordered_worker_failure_is_typed_and_does_not_include_input() -> None:
    def fail_on_secret(value: str) -> str:
        if value == "PRIVATE PAGE TEXT":
            raise RuntimeError("do not expose worker error detail")
        return value

    with pytest.raises(DataflowExecutionError) as caught:
        map_ordered(
            ["ok", "PRIVATE PAGE TEXT", "not-submitted"],
            fail_on_secret,
            workers=2,
            executor="thread",
        )

    assert caught.value.index == 1
    assert caught.value.reason == "worker_exception"
    assert caught.value.timed_out is False
    assert "PRIVATE PAGE TEXT" not in str(caught.value)
    assert "do not expose" not in str(caught.value)


def test_map_ordered_submission_failure_is_typed_without_worker_details():
    class RejectingPool(ThreadPoolExecutor):
        def submit(self, *_args, **_kwargs):
            raise RuntimeError("private submission diagnostics")

    pool = RejectingPool(max_workers=1)
    try:
        with pytest.raises(DataflowExecutionError) as caught:
            map_ordered(["private page data"], _square, workers=1, executor="thread", pool=pool)
        assert caught.value.index == 0
        assert caught.value.reason == "worker_exception"
        assert "private submission diagnostics" not in str(caught.value)
        assert "private page data" not in str(caught.value)
    finally:
        pool.shutdown()


def test_map_ordered_timeout_discards_late_thread_result() -> None:
    def delayed(value: int) -> int:
        time.sleep(0.15)
        return value

    started = time.perf_counter()
    with pytest.raises(DataflowExecutionError) as caught:
        map_ordered([7, 8], delayed, workers=1, executor="thread", timeout_s=0.02)

    assert time.perf_counter() - started < 0.12
    assert caught.value.index == 0
    assert caught.value.reason == "timeout"
    assert caught.value.timed_out is True
