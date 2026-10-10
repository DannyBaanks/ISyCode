# Browser Dataflow — M4 comparative decision

**Date:** 2026-10-09 (America/Mexico_City)
**Status:** User approved opt-in-only workers on 2026-10-09; final verification passed.
**Scope:** Compare M0 serial baseline, M1 serial chunking, M2 bounded executors, and M3 category/preview review. The regular browser action remains serial.

## Recommendation

**Keep workers as an explicit opt-in experiment; keep serial as the only normal browser path.** Do not set a worker default or automatic size threshold yet. M2/M3 show repeatable process-pool gains on some large inputs, but no general win: threads regress, small inputs lose to process overhead, scaling is uneven, and sampled process RSS reaches about 195 MB. A threshold and persistent pool would add lifecycle/concurrency behavior these measurements do not validate.

Serial chunking reproduces legacy output in the tested sample, but it did not improve latency and often made it worse. Keep its current experimental API only alongside the opt-in worker experiment; do not route ordinary browser reads through it based on this evidence. Alternatives are “retain chunks but drop workers” or “discard both additions.”

## Method, environment, and privacy

- All implementation experiments ran in isolated worktree `/tmp/isycode-webfetch-403`, branch `codex/webfetch-403`, base `6a206b0`; Linux x86_64, Python 3.12.3, Playwright 1.63.0, Chromium 153.0.8010.12 for M1–M3. M0 used Chromium 154.0.8037.97. These are host-specific results.
- M0: five in-memory page captures, then five serial filter runs per snapshot; see M0 report for its exact harness. M1 exact command: `PYTHONPATH=src python3 .superpowers/sdd/2026-10-09-isycode-dataflow-browser-chunks/compare_m1.py`.
- M2 exact command: `python3 scripts/benchmark_browser_read_dataflow.py > /tmp/isycode-browser-dataflow-m2-metrics-spawn.json`. It ran five repetitions per mode and measured cold pools (startup/shutdown included) and reused pools (excluded). Process pools use `spawn`; an earlier `fork` attempt warned and was discarded.
- M3 exact command: `python3 scripts/review_browser_read_generalization.py > /tmp/isycode-browser-read-m3-metrics-final.json`. It ran three repetitions with reused pools and tested the actual preview widget's exact-text display, discard, and share outcomes.
- M0/M1/M2 used five repetitions; M3 used three. Across milestones, same-input comparisons are claimed only when input SHA-256 matches. Different hashes are recaptures and are not directly compared. Process RSS is a separate, untimed child-process sample, not a guaranteed peak. `tracemalloc` does not measure browser/system memory.
- Live snapshots stayed in memory only. Reports/artifacts contain hashes, sizes, statuses, canaries, timing, and memory metadata, not raw/filtered page text. No page content was sent to a model.

## Snapshot identity across milestones

Matching hashes mean byte-identical captures. Different hashes are separate recaptures.

| Page | M0 SHA-256 | M1 SHA-256 | M2 SHA-256 | M3 SHA-256 |
|---|---|---|---|---|
| Python asyncio docs | `6bf337c3b0a9fb69cc9462460b137baa62585d3f8214f15aa351fb1347ed3c26` | `95ead4a1edb9f3f2d274e7a7d73d132f9120999f515cf21ea231d5bdcbc48c58` | `95ead4a1edb9f3f2d274e7a7d73d132f9120999f515cf21ea231d5bdcbc48c58` | `95ead4a1edb9f3f2d274e7a7d73d132f9120999f515cf21ea231d5bdcbc48c58` |
| CPython raw README | `839edf2c2f4532ad12880af349896fc0386edf105a6f81b3d349ee45f10b5817` | `839edf2c2f4532ad12880af349896fc0386edf105a6f81b3d349ee45f10b5817` | `839edf2c2f4532ad12880af349896fc0386edf105a6f81b3d349ee45f10b5817` | `839edf2c2f4532ad12880af349896fc0386edf105a6f81b3d349ee45f10b5817` |
| BBC News | `496687198ceb1e4bd02a867a41899d1f34304341bc08e4c673804984aff40b5c` | `89ebc52d95a53a7306a3b1d7d8282602d7474e226099d9910623829f5fd5d48d` | `e39e5f9ed2cd00624fd7b4fbecb48110fea543c2d362126bece08a72e2291a50` | `6a8ec46fa91a40c228bdc36f9da650bb196d49a098e1b6fb8e670d5afe93aeb4` |
| Wikipedia: Artificial intelligence | `1bdeb2a0eefad10bfdfc067805dc08869d5a5b5fb9a74302a75dd50ef8407cf3` | `81cd11517b15331009145906cf95da59c19a73488d873ba07a78aa066e46cca6` | `2b55841c245f9cabbe65561c4ada64f3dd831ebfa710d3bfb471ae43cd8a6720` | `bb4d55ee1fdc0798da52ef9d3464c5415eb98ca35deb5e7d5f19fdf6c785c652` |
| NVIDIA GeForce page | `24adfe6b74af8aa4c3f4f5fb0ea3cf50a197fb34e5e6bfb51b01561c9cc0dc90` | `24adfe6b74af8aa4c3f4f5fb0ea3cf50a197fb34e5e6bfb51b01561c9cc0dc90` | `24adfe6b74af8aa4c3f4f5fb0ea3cf50a197fb34e5e6bfb51b01561c9cc0dc90` | `24adfe6b74af8aa4c3f4f5fb0ea3cf50a197fb34e5e6bfb51b01561c9cc0dc90` |

README and NVIDIA are identical across M0–M3; Python docs are identical from M1 onward. BBC and Wikipedia recaptures differ after M0, so their cross-milestone timings are not like-for-like.

## Exact-input timing comparison

Median milliseconds. M1 compares legacy and chunked implementations on identical bytes. M2/M3 compare chunked serial with reused pools; pool startup/shutdown is excluded. RSS is a separate sample in bytes.

| Exact input (hash prefix) | M1 legacy → chunked | M2 chunked serial | M2 process ×2 / ×4 (×4 RSS) | M3 chunked serial | M3 process ×2 / ×4 (×4 RSS) |
|---|---:|---:|---:|---:|---:|
| Python docs (`95ead4a1…`) | 0.743 → 1.235 | 5.820 | 4.720 / 4.227 (65,282,048) | 5.945 | 4.266 / 4.803 (73,572,352) |
| CPython README (`839edf2c…`) | 0.945 → 0.915 | 3.241 | 1.268 / 1.326 (46,243,840) | 3.202 | 1.717 / 1.381 (59,744,256) |
| NVIDIA product (`24adfe6b…`) | 0.222 → 0.386 | 1.727 | 1.441 / 1.345 (45,068,288) | 1.806 | 1.620 / 1.541 (58,503,168) |

All exact-input comparisons produced the same output digests as their serial counterparts, with matching quality/truncation state and zero failures/timeouts. M1 chunking matched its legacy digest. M0 measured the same README and NVIDIA inputs at 3.300 ms and 0.857 ms; these are historical timings from a separate Chromium/Python session, not evidence of a performance regression. Threads did not improve on the exact shared inputs in M2/M3. Reused process results improved some medians but varied by page and worker count.

## Large inputs and recaptures

BBC and Wikipedia hashes changed, so these are within-milestone results only.

| Run / snapshot | Serial median | Process ×2 | Process ×4 | Process ×4 RSS | Outcome |
|---|---:|---:|---:|---:|---|
| M2 BBC, 32,458 chars, `e39e5f9e…` | 13.721 ms | 7.094 ms | 9.415 ms | 127,709,184 B | same digest/status; 2 workers beat 4 |
| M3 BBC, 32,385 chars, `6a8ec46f…` | 12.703 ms | 8.815 ms | 9.973 ms | 124,964,864 B | same digest/status; serial beat processes |
| M2 Wikipedia, 1,109,055 chars, `2b55841c…` | 344.664 ms | 195.375 ms | 174.470 ms | 142,233,600 B | every mode says `INCOMPLETE_TRUNCATED` |
| M3 Wikipedia, 635,002 chars, `bb4d55ee…` | 276.927 ms | 136.057 ms | 135.078 ms | 194,867,200 B | every mode says `INCOMPLETE_TRUNCATED` |

M2's separate 198,008-character synthetic fixture went from 117.895 ms serial to 49.657 ms with two reused processes and 48.079 ms with four. Its last canary lies beyond the 24,000-character cap. Cold process startup was costly on small inputs; M2's report records all cold/reused measurements. The faster results assume a reused pool, moving lifecycle and memory costs to a long-lived owner.

## Correctness and fidelity

- M1: serial chunks matched legacy output/status for all five pages and four fixtures in each same-input comparison. A nested skipped-subtree boundary mismatch was fixed with a regression test. The live Python capture lacked `create_task`; retention was not demonstrated.
- M2: all nine inputs had stable digests across executors, worker counts and pool modes, with zero recorded failures/timeouts. Truncation remained explicit.
- M3: six category fixtures passed their individual canaries in serial, thread and process modes, including useful `aside` content against noisy `main`. Outputs remained `untrusted=True` and `fidelity_assessed=False`.
- M3's five live captures returned HTTP 200. The preview showed exact serial-filtered text and discard/share returned the expected false/true decisions. This was a headless widget probe plus TUI tests, not manual human review of every page.
- Wikipedia stayed capped at 24,000 characters for every strategy. Workers do not recover omitted tail content. The synthetic API docs fixture preserved `create_task`, but the live Python capture did not contain it; live retention remains **NOT_DEMONSTRATED**.

## Claim ledger

- **DEMONSTRATED:** serial structural chunking reproduced legacy output/status on the recorded inputs, while retaining the global cap and explicit truncation.
- **DEMONSTRATED:** reused processes reduced filtering time on some large inputs, with stable ordering/output/status on this bounded sample.
- **FAILED as a general speedup claim:** serial chunking was slower on most M1 comparisons; threads did not help; process speed varied, worker scaling was non-monotonic, and cold startup regressed small pages.
- **FAILED as a memory-neutral claim:** sampled process RSS was about 45–195 MB. Full peaks under concurrent sessions were not measured.
- **DEMONSTRATED:** tested preview interactions display precisely the reviewed text and return the expected share/discard decision.
- **NOT_DEMONSTRATED:** universal semantic fidelity, recovery of omitted facts, manual review of live pages, perceived end-to-end speedup, concurrent-session memory safety, or a reliable automatic size threshold.
- **NOT_DEMONSTRATED:** whether a production worker pool is worth its lifecycle cost for the user's actual browser workflow.

## Validation and decision gate

- M3 focused suite: `python3 -m pytest tests/test_browser_read.py tests/test_dataflow.py tests/test_browser_read_benchmark.py tests/test_mcp_local.py -q -W default` → **80 passed in 22.17s**, no warnings.
- Final focused suite: `python3 -m pytest tests/test_dataflow.py tests/test_browser_read.py tests/test_mcp_local.py tests/test_browser_read_benchmark.py -q` → **80 passed in 21.75s**.
- Full non-integration suite: `python3 -m pytest -q -m "not integration"` → **1,853 passed, 0 failed, 1 skipped in 476.04s**.
- M3 live preview probe passed for all five captures. M0–M2 commands and focused results are recorded in their respective reports.
- Source inspection confirms `visible_tools` pins Playwright to `browser_snapshot`, and the normal browser action still calls legacy serial `filter_accessibility_snapshot`; no worker path was enabled. Tests assert the browser result filters the captured text before returning it, and benchmark serialization is metrics-only.
- `git diff --check` passed after the report and plan update.
- **Decision:** user approved opt-in-only workers while keeping serial normal. No path was switched and no experimental files were deleted. The existing chunk/executor API remains an explicit experiment; the browser action continues to use legacy serial filtering.
