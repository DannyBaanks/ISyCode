# Browser Dataflow — M2 bounded worker experiment

**Date:** 2026-10-09 (America/Mexico_City)
**Status:** M2 measured; waiting for the user's decision before M3.
**Scope:** Compare serial chunk filtering with bounded thread and process pools on the same in-memory snapshots. No workers are enabled in the normal browser path.

## Method and reproducibility

- Isolated worktree: `/tmp/isycode-webfetch-403`, branch `codex/webfetch-403`, based on `6a206b0`.
- Environment: Python 3.12.3, Linux x86_64, Playwright 1.63.0, Chromium 153.0.8010.12.
- Exact capture/benchmark command: `python3 scripts/benchmark_browser_read_dataflow.py > /tmp/isycode-browser-dataflow-m2-metrics-spawn.json`.
- The harness captured Python asyncio docs, CPython's raw README, BBC News, Wikipedia's Artificial Intelligence page, and NVIDIA GeForce graphics cards. It also ran four deterministic fixtures: small, 6,000-paragraph large, malformed, and useful-`aside`/noisy-`main` adversarial.
- For each input, it compared serial, thread pools (1/2/4 workers), and process pools (1/2/4 workers), with five repetitions. Cold pool rows include startup/shutdown; reused rows exclude pool lifecycle and warm a worker before timing. The five live pages returned HTTP 200.
- Timing reports median and empirical p95 of five samples. `tracemalloc` covers only the caller process. Process RSS is a separate untimed `psutil` sample, not part of the timing. A missing sample is recorded as `null`; it is not zero memory. Some cold short-lived workers were missed by the RSS sampler.
- Process pools use Python's `spawn` start method. An earlier trial with the Linux default `fork` emitted a `DeprecationWarning` because pytest already had threads; those measurements were discarded and replaced with the spawn run below. The focused suite with spawn passed without that warning.
- The saved metrics artifact contains hashes, sizes, booleans, timings, statuses, and memory metadata only. It has no page or filtered text. SHA-256: `3afd3e461c57977c54fc8d5033a3fadb600df48b15a41b31fa540eff6d5f8da7`.
- Reproduce live measurements with the command above; web content and its hash may change. The checked-in artifact is the captured run being assessed here.

## Results

Times are milliseconds as `median / p95`. Serial is the baseline. Process columns show reused pools at the stated worker count; the RSS column is the separate sampled worker RSS for the four-worker pool, where reported.

| Input | Chars | Serial | Process ×1 | Process ×2 | Process ×4 | Process RSS ×4 | Status / canaries |
|---|---:|---:|---:|---:|---:|---:|---|
| Python asyncio docs | 13,697 | 6.588 / 7.687 | 5.275 / 6.609 | 4.720 / 5.317 | 4.227 / 4.476 | 65,282,048 B | `create_task` missing; `asyncio` present |
| CPython README | 8,764 | 3.143 / 4.051 | 1.298 / 2.552 | 1.268 / 3.014 | 1.326 / 2.522 | 46,243,840 B | both canaries present |
| BBC News | 32,458 | 13.107 / 13.698 | 9.321 / 11.434 | 7.094 / 8.214 | 9.415 / 10.901 | 127,709,184 B | both canaries present |
| Wikipedia | 1,109,055 | 337.929 / 342.635 | 232.106 / 247.520 | 195.375 / 209.393 | 174.470 / 215.769 | 142,233,600 B | `INCOMPLETE_TRUNCATED`; both canaries present |
| NVIDIA product page | 4,309 | 1.673 / 2.805 | 1.384 / 2.147 | 1.441 / 2.829 | 1.345 / 2.172 | 45,068,288 B | both canaries present |
| Fixture: small | 39 | 0.054 / 0.103 | 0.460 / 0.664 | 0.320 / 0.482 | 0.328 / 0.689 | 45,051,904 B | canary present |
| Fixture: large | 198,008 | 117.895 / 121.837 | 57.475 / 59.822 | 49.657 / 54.363 | 48.079 / 55.235 | 140,959,744 B | `INCOMPLETE_TRUNCATED`; last canary beyond cap |
| Fixture: malformed | 71 | 0.169 / 0.264 | 0.284 / 0.915 | 0.539 / 0.874 | 0.342 / 0.855 | 45,064,192 B | both canaries present |
| Fixture: adversarial | 238 | 0.159 / 0.234 | 0.373 / 0.770 | 0.302 / 0.758 | 0.355 / 0.895 | 45,113,344 B | all three canaries present |

The RSS sample depends on which children were alive when sampled; it is not a guaranteed reservation or a full-process peak. Some cold process rows have no observation. The complete per-worker, cold/reused measurements and input/output hashes are in the JSON artifact.

## Correctness and safety observations

- All nine inputs had one output digest across every executor, worker count, pool lifecycle, and all five repetitions. Every row recorded zero worker failures and zero timeouts.
- Quality status and truncation were stable across modes. Wikipedia and the large fixture remained explicitly `INCOMPLETE_TRUNCATED`; workers did not bypass the 24,000-character cap.
- All canaries held except the known Python `create_task` miss and the large fixture's last item, which is outside the capped result. The missing Python canary is a fidelity limitation of the existing extractor; parallelism did not fix it.
- Worker errors return an incomplete result with no partial text. The regular browser call still selects serial defaults. The benchmark receives only the already-captured accessibility text; workers do not receive browser objects or tool capabilities.
- Raw live snapshots remained in memory only. The output JSON and this report do not contain page text. Human preview/consent remains unchanged; a live interactive preview was not part of this M2 run.

## Performance interpretation

- Threads did not beat serial meaningfully; the measured filter appears CPU-bound under the Python GIL, and thread scheduling adds overhead.
- Reused process pools substantially reduced latency for large inputs: Wikipedia was about 1.9× faster at four workers, and the large fixture about 2.5× faster. BBC improved at two workers but regressed again at four. The CPython README and Python docs also had lower medians in some process configurations, while the small, malformed, and adversarial fixtures became slower.
- Cold process pools add noticeable startup/shutdown cost, especially for small and medium pages. Reusing pools changes the lifecycle assumptions and carries substantial memory cost: sampled four-worker pools used roughly 45–142 MB across the inputs. Even one-worker pools added about 45 MB in the recorded reused-pool samples. Small inputs may activate fewer workers, explaining their lower RSS.
- Therefore M2 does **not** establish a safe general default. It demonstrates a speed/memory tradeoff for large snapshots, not a universal win or memory-neutral behavior. A size-thresholded, persistent process pool could be explored, but needs category-level adversarial and failure review before any normal-path adoption.

## Claim status

- **DEMONSTRATED:** bounded worker execution preserves deterministic output digests, source order, quality status, truncation, and canaries on this nine-input sample across serial/thread/process modes.
- **DEMONSTRATED:** reused process pools improve latency on the tested large snapshots; four workers helped Wikipedia and the large fixture, while two workers were the best BBC configuration. Worker count does not scale monotonically.
- **FAILED as a general-speedup hypothesis:** threads and cold process pools do not provide a general latency win; small fixtures are substantially slower with processes.
- **FAILED as a memory-neutral hypothesis:** process pools add substantial child-process RSS in the separate samples; full peak memory for cold short-lived workers was not always observed.
- **NOT_DEMONSTRATED:** broad semantic fidelity, user-visible speedup under real TUI interaction, stable thresholds across machines, memory behavior under concurrent browser sessions, or safety of enabling parallelism by default.

## Validation

- RED/GREEN worker and benchmark tests were recorded in the task harness; final focused suite: `python3 -m pytest tests/test_dataflow.py tests/test_browser_read.py tests/test_browser_read_benchmark.py tests/test_mcp_local.py -q -W default` → **50 passed in 5.61s**, no warnings.
- `git diff --check` passed before the report/plan updates; rerun after those edits.
- The metrics artifact's zero RSS observations from the initial serialization were corrected to `null` (“unavailable or not sampled”) before finalizing this report.

## M2 decision gate

M2 is complete. **Do not enable workers in the regular browser path yet.** Decide whether to continue to M3's category-specific adversarial/generalization review, adjust the experiment, or discard the worker implementation. No M3 work has started.
