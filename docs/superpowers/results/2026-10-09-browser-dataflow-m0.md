# Browser Dataflow — M0 serial baseline

**Date:** 2026-10-09 (America/Mexico_City)

**Status:** M0 measured; M1 was approved by the user on 2026-10-09 and completed in the companion M1 report.

**Scope:** Existing serial accessibility snapshot filter and its timing display. No worker or chunk implementation.

## Environment and method

- Worktree: `/tmp/isycode-webfetch-403`, branch `codex/webfetch-403`, base `6a206b0`.
- Python 3.12.3, Playwright 1.63.0, Google Chrome 154.0.8037.97, Linux x86_64, 12 logical CPUs.
- Public pages were captured with local headless Chromium using `page.goto(..., wait_until="commit")`, a 4-second settle, and `body.aria_snapshot()`. Each snapshot stayed in memory; the local filter ran five times on the same bytes. The report stores hashes and metrics only.
- Capture time includes navigation, settle, and accessibility snapshot. `filter_ms_median` is the median of five local filter runs; network time is excluded. `python_peak_bytes` is `tracemalloc` peak during filtering, not whole-browser memory.
- The five chosen pages represent docs, a GitHub-hosted README, news, Wikipedia, and a product page. The GitHub README was served from `raw.githubusercontent.com` because GitHub's rendered repository page exposed only a 55-character accessibility snapshot to this headless run.
- The exact-text preview and discard/share behavior was checked through the existing TUI test path. These public page contents were not sent to any model, and the live UI approval screen was not manually operated during capture.

## Public page results

| Category and URL | HTTP | Snapshot → filtered chars | Capture ms | Filter median ms (max) | Python peak bytes | Truncated | Canary results |
|---|---:|---:|---:|---:|---:|---|---|
| [Python asyncio docs](https://docs.python.org/3/library/asyncio.html) | 200 | 11,226 → 3,150 | 11,912 | 3.221 (3.732) | 52,119 | No | `asyncio` ✓; `create_task` ✗ |
| [CPython README](https://raw.githubusercontent.com/python/cpython/main/README.rst) | 200 | 8,764 → 8,748 | 12,045 | 3.300 (4.001) | 1,435,087 | No | `python` ✓; `cpython` ✓ |
| [BBC News](https://www.bbc.com/news) | 200 | 32,453 → 14,530 | 17,994 | 8.633 (9.445) | 181,076 | No | `news` ✓; `world` ✓ |
| [Wikipedia: Artificial intelligence](https://en.wikipedia.org/wiki/Artificial_intelligence) | 200 | 828,826 → 23,739 | 18,032 | 179.128 (186.417) | 2,240,113 | Yes, `INCOMPLETE_TRUNCATED` | `artificial intelligence` ✓; `machine learning` ✓ |
| [NVIDIA GeForce graphics cards](https://www.nvidia.com/en-us/geforce/graphics-cards/) | 200 | 4,309 → 743 | 35,230 | 0.857 (0.946) | 17,170 | No | `geforce` ✓; `graphics` ✓ |

Snapshot SHA-256 values, in table order:

1. `6bf337c3b0a9fb69cc9462460b137baa62585d3f8214f15aa351fb1347ed3c26`
2. `839edf2c2f4532ad12880af349896fc0386edf105a6f81b3d349ee45f10b5817`
3. `496687198ceb1e4bd02a867a41899d1f34304341bc08e4c673804984aff40b5c`
4. `1bdeb2a0eefad10bfdfc067805dc08869d5a5b5fb9a74302a75dd50ef8407cf3`
5. `24adfe6b74af8aa4c3f4f5fb0ea3cf50a197fb34e5e6bfb51b01561c9cc0dc90`

All five repeated runs per captured page produced the same filtered-output digest. Output digests, in table order:

1. `f57e37a1ae71878d631d35a4f46280bcc68e7b660fe66284b6090c8631b6847d`
2. `f3237f930e4d7015598ddf847eb81696d3c0de2bcba1a686eaa081944b556e28`
3. `eb4ecd092fc1de04afc44daac3c3573736ba989896e0c2effc1b8e499fec8109`
4. `453eab0d2e3a8738339de7b7e8c0aa6ff64d0534760a1cd19a01f1179d94ad88`
5. `384e8a112e8e7bf6282c4348f9b8d48bf9635fbd1d148ab2d7c559f5308500d2`

## Synthetic fixtures

Each deterministic fixture was filtered five times from the same in-memory bytes. All five output digests matched. Fixture source and page text were not written to disk.

| Fixture | Input → output chars | Median ms | Python peak bytes | Truncated | Canaries |
|---|---:|---:|---:|---|---|
| Small | 71 → 35 | 0.049 | 3,110 | No | small-page text ✓ |
| Large, 6,000 unique paragraphs | 427,373 → 23,989 | 156.108 | 1,364,374 | Yes, `INCOMPLETE_TRUNCATED` | first item ✓; last item ✗ because of global cap |
| Malformed lines mixed with valid nodes | 139 → 75 | 0.057 | 7,096 | No | valid heading ✓; valid body ✓ |
| Adversarial `aside` / `main` | 229 → 125 | 0.090 | 3,695 | No | useful `aside` text ✓; untrusted `main` text remains ✓ |

Fixture input SHA-256 values:

- Small: `6baaae752e6e3566c28c7366d63895bc091ef6b5225da95193fa0d424c2cbeee`
- Large: `093f065b8985b938c1b2dcbcdb867a6750de9ac84ec91dd5b4346e5f1aba0e77`
- Malformed: `ac2365c6c643b4357a80f9033125a57dde024acd616a7a05a8d2ff5d93630145`
- Adversarial: `21264bf06d5e445dcb39ea3919d8de535789dff2e31f2fe9f0743b18b3cc6855`

## Validation and negative results

- RED was observed for `test_filter_reports_nonnegative_processing_duration`: `KeyError: 'processing_ms'` before the implementation.
- GREEN: `python3 -m pytest tests/test_browser_read.py tests/test_mcp_local.py -q` → **22 passed**.
- The preview test confirms the duration is displayed and that decline still returns `content_shared: false`; the MCP test confirms only filtered content reaches the result and the raw snapshot is absent.
- Initial attempts to capture the rendered GitHub repository, The Guardian, and Apple's product page timed out or yielded a 55-character GitHub snapshot. The GitHub-hosted raw README, BBC, and NVIDIA pages supplied usable replacements. These results describe this headless network run; they do not prove those sites block all browsers.
- The Python docs canary `create_task` was absent despite the `asyncio` canary surviving. This is a fidelity miss to carry into M3, not a passing fidelity claim.
- Wikipedia's 828,826-character snapshot was reduced to 23,739 characters and correctly marked incomplete. The filter did not remove its global cap.
- The README snapshot was reduced by only 16 characters. The current filter is not a general Markdown compressor for raw text pages.

## Claim status

- **DEMONSTRATED:** local filtering duration is measurable and reaches the reviewed preview without adding raw snapshot text.
- **DEMONSTRATED:** identical snapshot bytes yield stable filtered-output digests across five serial runs in this sample.
- **DEMONSTRATED:** output truncation and `INCOMPLETE_TRUNCATED` appear for the large page and fixture.
- **DEMONSTRATED:** selected useful and adversarial text canaries survive in these captures/fixtures; the specific Python `create_task` canary did not.
- **NOT_DEMONSTRATED:** semantic fidelity across arbitrary pages, live manual preview operation during actual captures, and any speed improvement from chunks or workers.
- **NOT_DEMONSTRATED:** whole-browser memory use or end-to-end latency to the model. Capture/network time is reported separately from local filter time.

## Decision requested

M0 supplied a repeatable local baseline and confirmed a workload range from sub-millisecond fixtures to about 179 ms for an 828K-character snapshot. It recorded one missed docs canary, a rendered GitHub snapshot failure, and the existing output cap. The M0 gate was approved; M1's comparison and separate decision gate are in `2026-10-09-browser-dataflow-m1.md`.
