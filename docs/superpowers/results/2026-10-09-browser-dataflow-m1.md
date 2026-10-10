# Browser Dataflow — M1 serial chunk comparison

**Date:** 2026-10-09 (America/Mexico_City)
**Status:** M1 measured; awaiting the user's decision before M2.
**Scope:** Structural line chunks, inherited tree/skip state, serial filtering and source-order reassembly. No workers or browser-path adoption.

## Environment and method

- Worktree: `/tmp/isycode-webfetch-403`, branch `codex/webfetch-403`, source base `6a206b0`.
- Python 3.12.3, Playwright 1.63.0, Chromium 153.0.8010.12, Linux x86_64.
- Reproducible in-memory harness: `.superpowers/sdd/2026-10-09-isycode-dataflow-browser-chunks/compare_m1.py`.
- Exact command: `PYTHONPATH=src python3 .superpowers/sdd/2026-10-09-isycode-dataflow-browser-chunks/compare_m1.py`.
- For each comparison, the same snapshot string was passed to both implementations. The harness ran five alternating legacy/chunked measurements and emitted medians, input SHA-256, output sizes/digests, truncation status, and canaries. It did not persist or print snapshot/page text.
- Public pages used local headless Chromium, `page.goto(..., wait_until="commit")`, a 2-second settle, and `body.aria_snapshot()`. Capture/network time is excluded from filter timing.
- Memory is Python `tracemalloc` peak for one deterministic synthetic large fixture only; browser-process memory was not measured.
- M0's 427,373-character large fixture was not available as raw input, so M1 used a newly generated 198,008-character fixture. Do not compare these as byte-identical fixtures.

## Public page comparisons

| Category | HTTP | Input → output chars | Legacy median ms | Chunked median ms | Status equal | Output digest equal | Canary results |
|---|---:|---:|---:|---:|---|---|---|
| Python asyncio docs | 200 | 13,697 → 3,150 | 0.743 | 1.235 | Yes | Yes | `asyncio` ✓; `create_task` ✗ |
| CPython raw README | 200 | 8,764 → 8,748 | 0.945 | 0.915 | Yes | Yes | `python` ✓; `cpython` ✓ |
| BBC News | 200 | 32,469 → 14,546 | 2.287 | 3.224 | Yes | Yes | `news` ✓; `world` ✓ |
| Wikipedia: Artificial intelligence | 200 | 685,406 → 23,961 | 42.481 | 61.985 | Yes, `INCOMPLETE_TRUNCATED` | Yes | `artificial intelligence` ✓; `machine learning` ✓ |
| NVIDIA GeForce cards | 200 | 4,309 → 743 | 0.222 | 0.386 | Yes | Yes | `geforce` ✓; `graphics` ✓ |

Input SHA-256 in table order:

1. `95ead4a1edb9f3f2d274e7a7d73d132f9120999f515cf21ea231d5bdcbc48c58`
2. `839edf2c2f4532ad12880af349896fc0386edf105a6f81b3d349ee45f10b5817`
3. `89ebc52d95a53a7306a3b1d7d8282602d7474e226099d9910623829f5fd5d48d`
4. `81cd11517b15331009145906cf95da59c19a73488d873ba07a78aa066e46cca6`
5. `24adfe6b74af8aa4c3f4f5fb0ea3cf50a197fb34e5e6bfb51b01561c9cc0dc90`

Each reported public-page input produced identical legacy and chunked output digests and statuses in all five repetitions. Recaptures can change between runs; only rows within this M1 report compare identical in-memory snapshot bytes.

## Deterministic fixtures

| Fixture | Input → output chars | Legacy median ms | Chunked median ms | Same output/status in 5 runs | Canaries |
|---|---:|---:|---:|---|---|
| Small | 39 → 15 | 0.005 | 0.012 | Yes | small-page text ✓ |
| Large, 6,000 unique paragraphs | 198,008 → 23,993 | 16.972 | 20.845 | Yes, `INCOMPLETE_TRUNCATED` | first item ✓; last item ✗ due to global cap |
| Malformed lines with valid nodes | 71 → 24 | 0.007 | 0.013 | Yes | valid heading ✓; valid body ✓ |
| Adversarial useful aside / main | 238 → 74 | 0.020 | 0.032 | Yes | API reference ✓; Retry-After ✓; useful main text ✓ |

Fixture input SHA-256 in table order:

1. `67c5dfc4c4fab60e929ecede419358f4cbc8de45688677a0be2ca750b949802d`
2. `a17e97394b29064f52be28c6e89e1eb6a50f87fde6706e7337bc8ea66340e831`
3. `69e2daa3fcc0656026a5607015719741b484868e685d2e0ad0a641afddfc53c8`
4. `d106f5a66472a56d0de7b67f095b7feb1a9e4a96d5186fab945e3e0a17ac5a7f`

Python `tracemalloc` peak on the 198,008-character fixture: legacy **893,674 bytes**, chunked **873,296 bytes**. This single-process fixture measurement does not establish whole-program or browser memory behavior.

## Findings and validation

- The serial chunked implementation preserved legacy content and quality status on all five public-page captures and all four deterministic fixtures in the final harness run. It preserved the 24,000-character global cap and `INCOMPLETE_TRUNCATED` status.
- Serial chunking was slower on four of five live pages and all four fixtures in this sample; the README was effectively tied. For the large Wikipedia capture, median filter time rose from 42.481 ms to 61.985 ms. One fixture showed a modest Python allocation peak reduction, which does not offset the measured serial latency by itself.
- An exploratory BBC comparison first exposed a mismatch: nested skipped roles carried different state across chunk boundaries. The splitter now carries the legacy filter's effective single skip-depth state, with a regression test; the final five-page comparison produced identical output digests.
- RED was observed before Task 2 implementation (`ModuleNotFoundError: isycode.dataflow`) and before Task 3 implementation (`ImportError` for the missing chunked function).
- GREEN: `python3 -m pytest tests/test_dataflow.py tests/test_browser_read.py -q` → **18 passed** (after adding the nested skip-depth regression; Task 3's recorded run before that final test was 17 passed).
- `git diff --check` passed before the last test-only addition; rerun in final M1 verification.
- The Python docs `create_task` canary remains absent. This is an existing fidelity miss, not caused by chunking.
- Raw snapshots were held in memory only. No page text was sent to a model or saved in this report or the harness output.

## Claim status

- **DEMONSTRATED:** structural splitting reconstructs source text exactly, preserves whole lines, carries ancestor and skip state, and keeps oversized lines intact.
- **DEMONSTRATED:** serial chunked filtering matched legacy output digests and statuses for this M1 sample, including over-cap cases, across five repetitions per input.
- **DEMONSTRATED:** the existing global cap remains in force; chunks do not recover content beyond it.
- **NOT_DEMONSTRATED:** general semantic fidelity beyond the recorded page/fixture canaries, performance improvement, whole-browser memory behavior, or benefits from worker parallelism.
- **FAILED (as a speed-up hypothesis for serial chunking):** this sample shows no repeatable serial latency advantage; most measured inputs were slower.

## Decision gate

M1 establishes semantic equivalence for this bounded sample and adds the chunk interface needed to evaluate workers. It does not show that serial chunking is faster. **Stop here and ask whether to continue to M2's bounded worker experiment, adjust M1, or discard it.**
