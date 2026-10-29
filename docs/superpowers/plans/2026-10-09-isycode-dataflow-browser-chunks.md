# ISyCode Browser Dataflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether structural chunks and an ordered, bounded Dataflow worker pool improve processing of large Playwright accessibility snapshots while preserving filtering, truncation, and human-review guarantees.

**Architecture:** First make the existing serial filter measurable. Then add structural chunking and compare it serially with the legacy filter. Only after that, add an in-process ordered-map primitive with a bounded number of submitted tasks. Each worker receives immutable text and structural context, returns an indexed result, and the coordinator validates and joins results in source order. Benchmark serial, thread, and process execution on the same in-memory snapshots. Parallel execution remains experimental unless repeated measurements justify adoption.

**Tech Stack:** Python 3.10+, standard library (`concurrent.futures`, `time`, `hashlib`), existing pytest suite; no new runtime dependency, network client, durable queue, or browser control.

**Spec:** `docs/superpowers/specs/2026-10-09-isycode-dataflow-browser-chunks-design.md`

## Global Constraints

- First consumer is the existing read-only Playwright accessibility snapshot path.
- Workers receive page text only; they never receive browser objects, credentials, or tool capabilities.
- Do not persist raw snapshots or page text in benchmark artifacts.
- Preserve stable chunk order, the explicit global output cap, `INCOMPLETE_TRUNCATED`, `untrusted`, and the existing human preview/consent flow.
- Missing, failed, timed-out, or cancelled chunks make the aggregate incomplete; never publish a partial aggregate as complete.
- Keep concurrency bounded; choose its default only from comparative measurements.
- Chunking does not raise the global output cap or increase model context. A result that exceeds the cap remains explicitly truncated.
- Do not integrate Dataflow into other ISyCode tools in this plan.
- Stop after every milestone and wait for the user's decision to continue, adjust, or discard.

## Review Focus

- A chunk boundary lands inside a skipped accessibility subtree; test that descendants remain skipped in the next chunk.
- A malformed, empty, or very large single-line snapshot arrives; test deterministic output and explicit status without unbounded chunk growth.
- A worker completes out of order or fails; test source-order join and fail-closed aggregate status.
- Duplicate text falls on a chunk boundary, including Unicode text; test boundary deduplication without corrupting characters.
- A page category places useful text in `aside` and noise in `main`; test canaries individually and do not let aggregate averages hide a miss.

---

## Milestone 0 — Reproducible serial baseline

**Decision gate:** Continue only when the current serial filter can be compared repeatably on the same five page snapshots and local fixtures. No algorithm or worker changes in this milestone.

### Task 1: Expose local filtering duration in the reviewed preview

**Files:**
- Modify: `src/isycode/browser_read.py`
- Test: `tests/test_browser_read.py`
- Modify: `src/isycode/tui_app_tools.py`
- Modify: `src/isycode/tui_screens_approval.py`
- Test: `tests/test_mcp_local.py`

**Interfaces:**
- `filter_accessibility_snapshot(snapshot: str, *, max_chars: int = MAX_BROWSER_TEXT) -> dict` adds `processing_ms: float` measured with `time.perf_counter()` around filtering. It must not include network wait or preview time.
- `mcp_local.py` already spreads the filter result into the MCP response, so no production change is needed there. It must continue returning no raw snapshot.
- `TUIApp` forwards the optional duration to `BrowserReadPreviewScreen`; the preview shows it beside input/output sizes. Older/mock payloads without the field remain valid.

- [x] **Step 1: Add `test_filter_reports_nonnegative_processing_duration`** asserting the metric is numeric, finite, and `>= 0` while existing content and quality assertions remain unchanged.
- [x] **Step 2: Run `python3 -m pytest tests/test_browser_read.py::test_filter_reports_nonnegative_processing_duration -q`** and confirm it fails because the field is absent.
- [x] **Step 3: Add the minimal timer to `filter_accessibility_snapshot`** and include `processing_ms` in its result.
- [x] **Step 4: Extend `test_playwright_snapshot_is_filtered_before_it_reaches_chat`** to assert the successful browser result contains the duration and filtered content but not the original snapshot.
- [x] **Step 5: Forward the optional duration to the browser preview and add an assertion that the duration appears in its warning.** Preserve exact-content review and discard behavior.
- [x] **Step 6: Run `python3 -m pytest tests/test_browser_read.py tests/test_mcp_local.py -q`** and confirm both files pass.
- [x] **Step 7: Capture the five public page categories in an isolated headless Playwright Chromium and run the local filter only** (Python documentation, GitHub-hosted README, news, Wikipedia, product page). Record URL, capture time, input/output sizes, duration, truncation, canary results, and snapshot SHA-256 in a run report. Keep raw snapshots in memory only; no page text is sent to a model. Verify the reviewed preview/decline flow separately with the existing TUI test.
- [x] **Step 8: Run the baseline against synthetic small, large, malformed, and adversarial fixtures** and record the same metrics. Confirm reruns operate on identical fixture bytes.
- [x] **Step 9: Present M0 evidence and stop for the user's continue/adjust/discard decision.** The user approved M1 on 2026-10-09; do not advance beyond M1 without another decision.

**Milestone artifact:** A dated report under `docs/superpowers/results/` with commands, environment, metrics, hashes, negative results, and `NOT_DEMONSTRATED` claims. The report contains no raw page text. Live-page comparisons within a milestone use the same captured bytes in memory; later recaptures may differ and are labeled as such.

---

## Milestone 1 — Semantic chunking, still serial

**Decision gate:** Continue only if chunked serial output preserves all behavior for snapshots under the cap and reports over-cap output honestly.

### Task 2: Model structural chunks

**Files:**
- Create: `src/isycode/dataflow.py`
- Test: `tests/test_dataflow.py`

**Interfaces:**
- `DataflowChunk` is a frozen dataclass with `index: int`, `text: str`, and explicit inherited structural state, including active ancestor indentation and whether the chunk begins inside a skipped subtree.
- `DataflowChunkResult[T]` is a frozen dataclass with `index: int`, `value: T | None`, and `error: str | None`; exactly one of `value` or `error` is populated.
- `split_accessibility_snapshot(snapshot: str, *, target_chars: int) -> list[DataflowChunk]` partitions only at complete tree nodes/lines and records the active ancestor/skip context needed by the filter.

- [x] **Step 1: Add tests** for monotonically indexed chunks, exact reconstruction of source lines, target sizing except for a single oversized line, and inherited skip-subtree context.
- [x] **Step 2: Run `python3 -m pytest tests/test_dataflow.py -q`** and confirm the new imports/functions fail as expected.
- [x] **Step 3: Implement `DataflowChunk`, `DataflowChunkResult`, and `split_accessibility_snapshot`** without adding workers or changing the browser filter.
- [x] **Step 4: Add tests** for empty input, malformed lines, Unicode boundaries, and a giant single-line node. Verify the oversized line is represented as one chunk and is never silently dropped.
- [x] **Step 5: Run `python3 -m pytest tests/test_dataflow.py -q`** and confirm all splitter tests pass.

### Task 3: Filter and reassemble chunks serially

**Files:**
- Modify: `src/isycode/browser_read.py`
- Modify: `src/isycode/dataflow.py`
- Test: `tests/test_browser_read.py`
- Test: `tests/test_dataflow.py`

**Interfaces:**
- `filter_accessibility_chunk(chunk: DataflowChunk) -> DataflowChunkResult[str]` applies the existing role, subtree, UI-label, and plain-text rules using the chunk's inherited context.
- `filter_accessibility_snapshot_chunked(snapshot: str, *, max_chars: int = MAX_BROWSER_TEXT, target_chunk_chars: int = 8_000) -> dict` uses serial execution, validates every index, joins in source order, preserves the legacy adjacent-duplicate rule across chunk boundaries, then applies the global output cap and quality flags. It does not claim to recover content beyond that cap.

- [x] **Step 1: Add `test_chunked_filter_matches_legacy_filter_below_global_limit`** with a snapshot spanning multiple chunks and assert exact content and status equality.
- [x] **Step 2: Add tests** for skipped subtree boundaries, duplicate lines across chunks, global truncation after join, and no raw snapshot in output.
- [x] **Step 3: Run the focused tests and confirm failure** before implementation.
- [x] **Step 4: Implement serial chunk filtering and ordered join**; on any absent/error result, return `INCOMPLETE_DATAFLOW` with empty content, no misleading partial content, and `untrusted=True`.
- [x] **Step 5: Run `python3 -m pytest tests/test_dataflow.py tests/test_browser_read.py -q`** and confirm all focused tests pass.
- [x] **Step 6: Compare legacy and chunked serial filtering on identical fixture bytes and on each just-captured page snapshot**; record content diffs, canaries, truncation, elapsed time, and memory where available. Compare M0 live-page results as historical observations because later captures may have changed.
- [x] **Step 7: Present M1 evidence and stop for the user's decision.**

---

## Milestone 2 — Bounded worker experiment

**Decision gate:** Parallel processing is accepted only if it beats chunked serial processing repeatably without content, memory, or completion regressions. Otherwise retain serial chunking and discard parallel execution.

### Task 4: Add an ordered bounded map primitive

**Files:**
- Modify: `src/isycode/dataflow.py`
- Test: `tests/test_dataflow.py`

**Interfaces:**
- `map_ordered(items: Sequence[T], worker: Callable[[T], R], *, workers: int, executor: Literal["serial", "thread", "process"], timeout_s: float | None = None, pool: Executor | None = None) -> list[R]` returns results in input order, rejects nonpositive worker counts, and submits at most `workers` tasks at once. On a worker exception or deadline, it raises `DataflowExecutionError(index, reason, timed_out)` and cancels work that has not started; the browser caller converts this to an incomplete result with empty content. A deadline never publishes late results; already-running thread work may finish in the background and is discarded.
- When `pool` is omitted, `map_ordered` creates and closes a pool, so setup and shutdown are included. When supplied, it uses the caller-owned pool and leaves its lifecycle to the caller; reused-pool measurements must declare that setup/shutdown are excluded. Only the benchmark uses this injection path initially.
- The process worker must be a top-level picklable function. Owned process pools use the `spawn` start method to avoid forking the already-multithreaded TUI/provider process. A supplied pool must be the selected executor type; the caller is responsible for creating it with the requested worker count and safe lifecycle.
- `DataflowExecutionError` contains only the chunk index and a bounded error description, never the chunk text or page content.

- [x] **Step 1: Add tests** that deliberately finish tasks out of order, reject invalid worker counts, and verify serial equivalence for deterministic inputs.
- [x] **Step 2: Add worker failure and timeout tests** asserting a typed error identifies the failed chunk and pending tasks are cancelled; failures must not be silently dropped.
- [x] **Step 3: Run the new tests and confirm failure** before implementation.
- [x] **Step 4: Implement serial, thread-pool, and process-pool execution** with explicit ownership-aware pool shutdown, bounded submission, timeout handling, and stable ordering.
- [x] **Step 5: Run `python3 -m pytest tests/test_dataflow.py -q`** and confirm all worker tests pass.

### Task 5: Benchmark candidate workers on identical chunks

**Files:**
- Modify: `src/isycode/browser_read.py`
- Modify: `src/isycode/dataflow.py`
- Create: `scripts/benchmark_browser_read_dataflow.py`
- Test: `tests/test_browser_read_benchmark.py`

**Interfaces:**
- `benchmark_filter_modes(snapshot: str, *, workers: tuple[int, ...] = (1, 2, 4), repetitions: int = 5, pool_lifecycle: Literal["cold", "reused"] = "cold") -> list[dict]` runs serial, threads, and processes against the same captured snapshot; records wall time, peak memory when available, output digest/length, canaries, worker count, lifecycle mode, and whether pool setup/shutdown was included.
- Extend the interface to `filter_accessibility_snapshot_chunked(snapshot: str, *, max_chars: int = MAX_BROWSER_TEXT, target_chunk_chars: int = 8_000, executor: Literal["serial", "thread", "process"] = "serial", workers: int = 1, timeout_s: float | None = None, pool: Executor | None = None) -> dict`. The regular browser path continues using serial defaults until the final adoption gate.
- The benchmark returns metrics only; it never writes snapshot text or filtered page content to its report.

- [x] **Step 1: Add `test_benchmark_compares_identical_input_and_never_emits_page_text`** with a synthetic snapshot and assert all modes share its input digest while output has only metrics.
- [x] **Step 2: Add tests** for reproducible content digests, cold/reused-pool labeling, and explicit timeout/failure records.
- [x] **Step 3: Run `python3 -m pytest tests/test_browser_read_benchmark.py -q`** and confirm the tests fail before implementation.
- [x] **Step 4: Implement the benchmark runner**; include pool setup/shutdown in cold results and label caller-owned reused pools separately. Reuse one pool per mode only within the benchmark invocation, then close it in a `finally` path. Run each mode against identical snapshot bytes held in memory for that comparison.
- [x] **Step 5: Run `python3 -m pytest tests/test_dataflow.py tests/test_browser_read.py tests/test_browser_read_benchmark.py -q`**.
- [x] **Step 6: Run candidate modes on the same fixtures and five freshly captured live snapshots**; compare median and tail wall time, output digest/canaries, truncation, memory, and failures. Do not treat a faster partial or incorrect output as a win. Label later page recaptures as new inputs, not byte-identical M0 samples.
- [x] **Step 7: Present M2 evidence and stop.** Wait for approval before enabling a parallel mode in the normal browser path.

---

## Milestone 3 — Generalization and adversarial review

**Decision gate:** Each page category must pass its own canaries and human preview review; an aggregate score cannot hide a category failure.

### Task 6: Add structural and adversarial coverage

**Files:**
- Modify: `tests/test_browser_read.py`
- Modify: `tests/test_dataflow.py`
- Modify: `tests/test_browser_read_benchmark.py`

- [x] **Step 1: Add regression fixtures** for Python/API docs, GitHub/README, news, Wikipedia, and product pages. Fixtures are synthetic accessibility trees and contain no copied live-page body text.
- [x] **Step 2: Add the `aside`-important / `main`-noise adversarial case** and assert each expected canary per category, preserving `untrusted=True` and `fidelity_assessed=False`.
- [x] **Step 3: Run `python3 -m pytest tests/test_browser_read.py tests/test_dataflow.py tests/test_browser_read_benchmark.py -q`** and confirm the adversarial assertions fail if a canary is removed.
- [x] **Step 4: Run each supported strategy on all fixtures and freshly captured public pages**; record per-category results separately, and keep each strategy within a comparison on identical in-memory snapshot bytes.
- [x] **Step 5: Inspect the browser preview for each live page** and verify that discard still prevents sharing and approval shares exactly the previewed text.
- [x] **Step 6: Present M3 findings and stop for the user's decision.**

---

## Milestone 4 — Adoption decision

### Task 7: Produce the comparative decision report

**Files:**
- Create: `docs/superpowers/results/2026-10-09-browser-dataflow-comparison.md`
- Modify: `docs/GUIA.md` only if a strategy is approved for normal use

- [x] **Step 1: Compare M0 serial, M1 chunked serial, and approved M2 worker results** with per-page correctness/canaries, wall time, memory, truncation, and negative results. Separate identical-input comparisons within a milestone from observations across different page captures.
- [x] **Step 2: Record a per-claim status** (`DEMONSTRATED`, `NOT_DEMONSTRATED`, or `FAILED`), exact environment and commands, SHA-256 for input snapshots, and a statement that raw snapshots were not stored.
- [x] **Step 3: Recommend one outcome:** normal browser use, opt-in experiment, retain chunks but drop workers, or discard both additions.
- [x] **Step 4: Present the report and wait for explicit approval.** Do not enable the chosen strategy or delete rejected files before that decision.

---

## Final verification after milestone approval

- [x] Focused suite: `python3 -m pytest tests/test_dataflow.py tests/test_browser_read.py tests/test_mcp_local.py tests/test_browser_read_benchmark.py -q` → 80 passed.
- [x] Full non-integration suite: `python3 -m pytest -q -m "not integration"` → 1,853 passed, 0 failed, 1 skipped.
- [x] `git diff --check`
- [x] Verify that the browser action still uses only the pinned `browser_snapshot` MCP tool and that no snapshot body appears in logs or benchmark files; filtering is asserted before results return, and benchmark JSON stores metrics only.
- Commit only the reviewed paths for the approved milestone; never include other worktree changes.
