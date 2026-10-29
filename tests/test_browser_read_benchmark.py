from __future__ import annotations

import hashlib

import pytest

from isycode.browser_read_benchmark import benchmark_filter_modes


def test_benchmark_compares_identical_input_and_never_emits_page_text():
    snapshot = (
        "- main:\n"
        "  - heading \"Benchmark canary\" [level=1]\n"
        "  - paragraph: This secret snapshot phrase must remain private.\n"
    )

    rows = benchmark_filter_modes(
        snapshot,
        workers=(1, 2),
        repetitions=2,
        canaries=("Benchmark canary", "secret snapshot phrase"),
    )

    assert len(rows) == 5  # serial once, plus thread/process at each size
    assert {row["input_sha256"] for row in rows} == {hashlib.sha256(snapshot.encode()).hexdigest()}
    assert all(row["output_sha256"] == rows[0]["output_sha256"] for row in rows)
    assert all(row["canaries"] == {"Benchmark canary": True, "secret snapshot phrase": True} for row in rows)
    assert all("content" not in row and "snapshot" not in row for row in rows)
    assert "This secret snapshot phrase" not in repr(rows)


def test_benchmark_labels_cold_and_reused_pool_measurements():
    snapshot = "- main:\n  - paragraph: stable benchmark output\n"

    cold = benchmark_filter_modes(snapshot, workers=(1,), repetitions=2, pool_lifecycle="cold")
    reused = benchmark_filter_modes(snapshot, workers=(1,), repetitions=2, pool_lifecycle="reused")

    cold_by_executor = {row["executor"]: row for row in cold}
    reused_by_executor = {row["executor"]: row for row in reused}
    assert cold_by_executor["thread"]["pool_lifecycle"] == "cold"
    assert cold_by_executor["thread"]["pool_setup_included"] is True
    assert reused_by_executor["thread"]["pool_lifecycle"] == "reused"
    assert reused_by_executor["thread"]["pool_setup_included"] is False
    assert cold_by_executor["serial"]["pool_lifecycle"] == "none"
    assert all(row["output_sha256"] == cold[0]["output_sha256"] for row in cold + reused)


def test_adversarial_sidebar_canaries_survive_every_executor():
    snapshot = (
        "- generic:\n"
        '  - complementary:\n    - heading "API reference" [level=2]\n'
        "    - paragraph: Retry-After accepts seconds.\n"
        "  - main:\n    - button \"Subscribe to alerts\":\n"
        "    - paragraph: Useful main documentation survives.\n"
    )

    rows = benchmark_filter_modes(
        snapshot,
        workers=(1, 2),
        repetitions=1,
        pool_lifecycle="reused",
        canaries=("API reference", "Retry-After", "Useful main documentation"),
    )

    assert {row["executor"] for row in rows} == {"serial", "thread", "process"}
    assert len({row["output_sha256"] for row in rows}) == 1
    assert all(all(row["canaries"].values()) for row in rows)
    assert all(row["quality_status"] == "UNASSESSED_REVIEW_REQUIRED" for row in rows)
    assert all("content" not in row for row in rows)


def test_benchmark_records_worker_failures_and_timeouts(monkeypatch):
    import isycode.browser_read as browser_read
    from isycode.dataflow import DataflowExecutionError

    def failed(*_args, **_kwargs):
        return {
            "content": "",
            "input_chars": 1,
            "filtered_chars": 0,
            "processing_ms": 1.0,
            "truncated": False,
            "quality_status": "INCOMPLETE_DATAFLOW",
            "fidelity_assessed": False,
            "untrusted": True,
            "dataflow_error": "chunk 0 failed",
        }

    monkeypatch.setattr(browser_read, "filter_accessibility_snapshot_chunked", failed)
    rows = benchmark_filter_modes("- main:\n", workers=(1,), repetitions=1)

    assert rows
    assert all(row["failures"] == 1 for row in rows)
    assert all(row["timeouts"] == 0 for row in rows)
    assert all(row["quality_status"] == "INCOMPLETE_DATAFLOW" for row in rows)
    assert all("content" not in row for row in rows)

    def timed_out(*_args, **_kwargs):
        raise DataflowExecutionError(2, "timeout", True)

    monkeypatch.setattr(browser_read, "filter_accessibility_snapshot_chunked", timed_out)
    timeout_rows = benchmark_filter_modes(
        "- main:\n", workers=(1,), repetitions=1, timeout_s=0.01
    )
    assert all(row["failures"] == 1 for row in timeout_rows)
    assert all(row["timeouts"] == 1 for row in timeout_rows)


@pytest.mark.parametrize("workers,repetitions", [((0,), 1), ((1,), 0), ((), 1)])
def test_benchmark_rejects_invalid_configuration(workers, repetitions):
    with pytest.raises(ValueError):
        benchmark_filter_modes("- main:\n", workers=workers, repetitions=repetitions)
