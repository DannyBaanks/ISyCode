# Browser Dataflow — M3 generalization and adversarial review

**Date:** 2026-10-09 (America/Mexico_City)
**Status:** M3 measured; no worker strategy approved for normal browser use.
**Scope:** Per-category synthetic fixtures, five fresh public captures, bounded executor equivalence, and exact preview/share/discard behavior. Raw snapshots and filtered live-page text were not persisted.

## Method

- Worktree: `/tmp/isycode-webfetch-403`, branch `codex/webfetch-403`.
- Environment: Python 3.12.3, Linux x86_64, Playwright 1.63.0, Chromium 153.0.8010.12.
- Focused tests: `python3 -m pytest tests/test_browser_read.py tests/test_dataflow.py tests/test_browser_read_benchmark.py tests/test_mcp_local.py -q -W default`.
- Live probe: `python3 scripts/review_browser_read_generalization.py > /tmp/isycode-browser-read-m3-metrics-final.json`.
- The probe captured all five pages before running CPU-heavy benchmarks, then compared serial, thread and `spawn` process modes with 2 and 4 workers. Each mode used the same in-memory input and three repetitions in a reused pool. Pool setup was excluded; M2 separately measures cold startup.
- Each live snapshot went through the actual `BrowserReadPreviewScreen` widget. The probe asserted that rendered text exactly equaled the serial filtered result, then clicked Discard and Share in separate runs and checked `false` / `true`. Existing TUI integration tests also verified the model-sharing gate for six category-shaped payloads.
- The JSON artifact contains page and fixture hashes, canary booleans, sizes, timing, status, and preview interaction outcomes. It contains no snapshot bodies or filtered page bodies. SHA-256: `746b6d83b5447ea7e43e23d4e1bbb0f11e1a77d996ec42944cbd1e25d504bb11`.

## Synthetic category fixtures

The regression cases cover API documentation, GitHub/README, news, Wikipedia, product information, and a hostile layout where the useful API reference is in `aside` while the `main` area contains a subscribe control and promotional noise. Each fixture was checked with serial, thread and process execution at 2 and 4 workers.

- All six fixtures preserved every expected per-category canary in every mode.
- The sidebar API title, `Retry-After`, and rate-limit example survived even with small chunk boundaries; the noisy subscribe subtree and promotional paragraph were omitted.
- Each result remained `untrusted=True`, `fidelity_assessed=False`, and `UNASSESSED_REVIEW_REQUIRED`; no fixture result claimed automatic fidelity certification.
- Every executor produced the same output digest for each fixture, with zero failures or timeouts.

Fixture input SHA-256 values:

| Category | Input SHA-256 |
|---|---|
| Python/API docs | `3d9943261165338d804dda15003fb364ec75c45c0d815c889c88cfb1ab71d30a` |
| GitHub/README | `271a045cfa9996ca9d5a540ac8c3f6c432dbb7a134d4946880ed7dff41b89fa2` |
| News | `58d6a1e9e99f0939862bb31e088a51f5af07e1064267fd2d968b4e0487e505bd` |
| Wikipedia | `ce9ac1160a499a93427f8c61d383779dd90ff3d92a4d54a5733aedd9dd44bd43` |
| Product page | `039a288ee294ebfd7555b3ee5a1bbb7fb31d414c1209a0b89584a5b5c81edc63` |
| Adversarial useful-aside/noisy-main | `1b15c819fd8296ea9d5a540ac8c3f6c432dbb7a134d4946880ed7dff41b89fa2` |

## Fresh public-page captures

`ms` columns show median / p95. Process RSS is sampled separately and may include fewer live children than the configured worker count. The full per-mode rows, output hashes, source canaries and capture metadata are in the JSON artifact.

| Page | Input chars | Input SHA-256 | Serial | Thread ×2 / ×4 | Process ×2 / ×4 | Status and canaries |
|---|---:|---|---:|---|---|---|
| Python asyncio docs | 13,697 | `95ead4a1edb9f3f2d274e7a7d73d132f9120999f515cf21ea231d5bdcbc48c58` | 5.945 / 6.721 | 6.429 / 6.899 · 6.486 / 6.694 | 4.266 / 5.994 · 4.803 / 5.678 | `asyncio` present; `create_task` absent from the captured source itself |
| CPython README | 8,764 | `839edf2c2f4532ad12880af349896fc0386edf105a6f81b3d349ee45f10b5817` | 3.202 / 3.246 | 4.034 / 4.569 · 3.377 / 3.484 | 1.717 / 3.199 · 1.381 / 2.682 | both canaries present |
| BBC News | 32,385 | `6a8ec46fa91a40c228bdc36f9da650bb196d49a098e1b6fb8e670d5afe93aeb4` | 12.703 / 12.774 | 14.944 / 16.132 · 16.472 / 17.289 | 8.815 / 9.657 · 9.973 / 11.402 | both canaries present |
| Wikipedia: Artificial intelligence | 635,002 | `bb4d55ee1fdc0798da52ef9d3464c5415eb98ca35deb5e7d5f19fdf6c785c652` | 276.927 / 278.191 | 273.689 / 273.807 · 306.050 / 315.888 | 136.057 / 142.569 · 135.078 / 141.649 | `INCOMPLETE_TRUNCATED`; both canaries present |
| NVIDIA GeForce product page | 4,309 | `24adfe6b74af8aa4c3f4f5fb0ea3cf50a197fb34e5e6bfb51b01561c9cc0dc90` | 1.806 / 1.871 | 1.816 / 2.593 · 2.285 / 3.009 | 1.620 / 3.418 · 1.541 / 2.214 | both canaries present |

All pages returned HTTP 200. Every category's strategy outputs had matching digests, stable statuses/truncation, and zero worker failures/timeouts. The Python docs capture had the same SHA-256 as the M0/M1 capture. `create_task` was also absent from the raw M3 snapshot, so the observed `false` is **not evidence that the filter removed it**; retention of that particular term remains NOT_DEMONSTRATED for this page capture. The synthetic API-docs fixture did preserve `create_task`.

Wikipedia remained explicitly truncated at the existing output cap in every mode. That is an expected incomplete result, not a successful full-page extraction.

## Human review path

For each of the five page captures, `displayed_exactly`, `discard_returns_false`, and `share_returns_true` were all true. Thus the preview rendered the exact serial-filtered text; discarding returned no share decision, and approving returned the share decision. The result remains explicitly untrusted and fidelity-unassessed. This is a headless Textual widget probe plus TUI integration tests, not a person manually reading every live page.

## Findings and claim status

- **DEMONSTRATED:** category-specific synthetic canaries and known-noise checks pass across serial, thread, and spawn-process strategies at the tested worker counts.
- **DEMONSTRATED:** useful content in a sidebar survives while known controls and promotional subtrees in `main` are filtered; small chunk boundaries preserve tree/skip context.
- **DEMONSTRATED:** the preview widget displays the exact reviewed text and its two actions return the expected decisions on all five live captures.
- **DEMONSTRATED:** all tested modes produce identical output digests per captured input and preserve status/truncation without worker failures or timeouts.
- **NOT_DEMONSTRATED:** complete semantic coverage of arbitrary pages. Canaries cover selected concepts, not every important fact. The live Python snapshot did not contain `create_task`, so that term's live-page retention cannot be inferred.
- **FAILED as a broad performance assumption:** threads did not improve page timings. Process pools improved some pages, most strongly Wikipedia, but consumed substantial RSS (about 195 MB sampled for its four-worker run); two workers were faster than four for BBC. Worker scaling is not monotonic.
- **NOT_DEMONSTRATED:** a safe global worker default, concurrent-user memory behavior, or meaningful user-perceived TUI speedup.

## Validation and decision

- Focused suite: **80 passed in 22.17s**, including category tests for all three executors and TUI share/discard tests for six category-shaped payloads.
- The live preview probe passed for all five pages; raw capture text was held in memory only.
- `git diff --check` is run as the final workspace check after report updates.
- **Recommendation:** retain serial as the normal path. The category tests support continuing to M4's whole-plan comparison, but M3 does not justify enabling parallel workers. Review whether to keep the experimental worker code, constrain it to an explicit opt-in/size threshold, or discard it before any rollout. This report stops at M3 and waits for the user's decision.
