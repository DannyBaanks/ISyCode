"""Metrics-only comparisons for serial and experimental Dataflow executors."""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import statistics
import threading
import time
import tracemalloc
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Literal

from . import browser_read
from .dataflow import DataflowExecutionError


def _warm_worker() -> None:
    """Force lazy thread/process startup outside reused-pool measurements."""


def _probe_process_worker_rss(call) -> int | None:
    """Sample Python child RSS separately from timed runs, if psutil is present."""
    try:
        import psutil
    except ImportError:
        return None

    root = psutil.Process()
    stopped = threading.Event()
    peak = [0]

    def sample() -> None:
        try:
            total = 0
            for child in root.children(recursive=False):
                try:
                    if child.name().lower().startswith(("python", "pypy")):
                        total += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            peak[0] = max(peak[0], total)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

    def monitor() -> None:
        sample()
        while not stopped.wait(0.002):
            sample()

    thread = threading.Thread(target=monitor, name="dataflow-rss-probe", daemon=True)
    thread.start()
    try:
        call()
    except Exception:
        return None
    finally:
        stopped.set()
        thread.join(timeout=1)
        sample()
    return peak[0] or None


def _valid_workers(values: tuple[int, ...]) -> bool:
    return bool(values) and all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in values
    ) and len(set(values)) == len(values)


def benchmark_filter_modes(
    snapshot: str,
    *,
    workers: tuple[int, ...] = (1, 2, 4),
    repetitions: int = 5,
    pool_lifecycle: Literal["cold", "reused"] = "cold",
    canaries: tuple[str, ...] = (),
    timeout_s: float | None = None,
) -> list[dict]:
    """Compare filter modes on one in-memory snapshot and emit metrics only.

    Cold measurements include per-call pool creation and shutdown. Reused
    measurements share one caller-owned pool per mode/size and exclude its
    lifecycle. `tracemalloc` reports Python allocations in this process; for
    process mode it does not include child-process memory.
    """
    if not isinstance(snapshot, str):
        raise TypeError("snapshot must be text")
    if not _valid_workers(workers):
        raise ValueError("workers must be a nonempty tuple of unique positive integers")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions <= 0:
        raise ValueError("repetitions must be a positive integer")
    if pool_lifecycle not in {"cold", "reused"}:
        raise ValueError("pool_lifecycle must be cold or reused")
    if timeout_s is not None and (
        not isinstance(timeout_s, (int, float))
        or isinstance(timeout_s, bool)
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ValueError("timeout_s must be a finite positive number")

    input_digest = hashlib.sha256(snapshot.encode()).hexdigest()
    configurations = [("serial", 1, "none")]
    for size in workers:
        configurations.extend(
            (("thread", size, pool_lifecycle), ("process", size, pool_lifecycle))
        )

    rows: list[dict] = []
    for executor, size, lifecycle in configurations:
        supplied_pool = None
        if lifecycle == "reused":
            pool_type = ThreadPoolExecutor if executor == "thread" else ProcessPoolExecutor
            supplied_pool = (
                pool_type(max_workers=size)
                if executor == "thread"
                else pool_type(
                    max_workers=size,
                    mp_context=multiprocessing.get_context("spawn"),
                )
            )
            # Executor construction alone does not start its worker threads or
            # child processes; complete a tiny task before starting the timer.
            supplied_pool.submit(_warm_worker).result()

        samples: list[float] = []
        peaks: list[int] = []
        output_digests: list[str] = []
        output_sizes: list[int] = []
        statuses: list[str] = []
        truncations: list[bool] = []
        canary_results = {canary: False for canary in canaries}
        failures = 0
        timeouts = 0
        try:
            for _ in range(repetitions):
                tracemalloc.start()
                started = time.perf_counter()
                try:
                    result = browser_read.filter_accessibility_snapshot_chunked(
                        snapshot,
                        executor=executor,
                        workers=size,
                        timeout_s=timeout_s,
                        pool=supplied_pool,
                    )
                except DataflowExecutionError as exc:
                    result = {
                        "content": "",
                        "quality_status": "INCOMPLETE_DATAFLOW",
                        "truncated": False,
                        "dataflow_error": f"chunk {exc.index} {exc.reason}",
                    }
                except Exception:
                    result = {
                        "content": "",
                        "quality_status": "INCOMPLETE_DATAFLOW",
                        "truncated": False,
                        "dataflow_error": "benchmark_execution_error",
                    }
                elapsed_ms = (time.perf_counter() - started) * 1000
                _current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()

                content = result.get("content", "")
                status = result.get("quality_status", "INCOMPLETE_DATAFLOW")
                failure = status == "INCOMPLETE_DATAFLOW"
                error = result.get("dataflow_error", "")
                samples.append(elapsed_ms)
                peaks.append(peak)
                output_digests.append(hashlib.sha256(content.encode()).hexdigest())
                output_sizes.append(len(content))
                statuses.append(status)
                truncations.append(bool(result.get("truncated", False)))
                failures += int(failure)
                timeouts += int(failure and "timeout" in error)
                canary_results = {
                    canary: canary.casefold() in content.casefold()
                    for canary in canaries
                }
            worker_rss_peak = None
            if executor == "process":
                worker_rss_peak = _probe_process_worker_rss(
                    lambda: browser_read.filter_accessibility_snapshot_chunked(
                        snapshot,
                        executor=executor,
                        workers=size,
                        timeout_s=timeout_s,
                        pool=supplied_pool,
                    )
                )
        finally:
            if supplied_pool is not None:
                supplied_pool.shutdown(wait=True, cancel_futures=True)

        ordered = sorted(samples)
        p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
        final_content_size = output_sizes[-1] if output_sizes else 0
        final_digest = output_digests[-1] if output_digests else hashlib.sha256(b"").hexdigest()
        final_status = statuses[-1] if statuses else "INCOMPLETE_DATAFLOW"
        rows.append(
            {
                "executor": executor,
                "workers": size,
                "pool_lifecycle": lifecycle,
                "pool_setup_included": lifecycle == "cold",
                "repetitions": repetitions,
                "timeout_s": timeout_s,
                "input_sha256": input_digest,
                "input_chars": len(snapshot),
                "output_sha256": final_digest,
                "output_chars": final_content_size,
                "digest_stable": len(set(output_digests)) <= 1,
                "quality_status": "INCOMPLETE_DATAFLOW" if failures else final_status,
                "truncated": any(truncations),
                "median_ms": round(statistics.median(samples), 3) if samples else 0.0,
                "p95_ms": round(ordered[p95_index], 3) if ordered else 0.0,
                "peak_python_bytes": max(peaks, default=0),
                "peak_worker_rss_bytes": worker_rss_peak,
                "worker_rss_probe": (
                    "psutil child-process RSS; separate untimed run"
                    if worker_rss_peak is not None
                    else "unavailable or not sampled"
                ),
                "memory_scope": (
                    "caller_process_only" if executor == "process" else "tracemalloc"
                ),
                "pool_startup_shutdown_in_timing": lifecycle == "cold",
                "canaries": canary_results,
                "failures": failures,
                "timeouts": timeouts,
            }
        )
    return rows
