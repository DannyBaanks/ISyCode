# Action-journal append cost — 2026-11-27

Script: `journal_append_bench.py <src-dir> <label>` (env `BENCH_DIR`). It fills one
active segment to ~4 MB with provider.request decision+receipt pairs, then times
40 more actions (one action = decision + receipt = two appends, two fsyncs).

Host under load during the run (load avg 15-26, IO pressure 50-90 %, `/` 99 % full),
so wall times are pessimistic; CPU time is the stable figure.

| build | segment | CPU / action (median) | wall median | wall p90 |
|---|---|---|---|---|
| `main` 0eba124 | 4.01 MB | 128.8 ms | 149.4 ms | 163.2 ms |
| branch, Python path (`ISYCODE_NATIVE_JOURNAL=0`) | 4.01 MB | 1.4 ms | 3.4 ms | 5.4 ms |
| branch, Zig `libisyjournal` | 4.01 MB | 1.2 ms | 2.7 ms | 3.3 ms |

Reading: the verified-tail cache removes the re-hash of the whole segment on
every append (~90x on CPU). The Zig write+fsync path adds a further ~20 % on
wall time; it is optional and falls back to Python. Neither removes fsync latency
under disk pressure, which is why the hot callers also moved off the Textual
thread (see `journal-ui-thread-probe-2026-11-27.tsv` and the after-probe).

## UI-thread probe, before vs after moving the hot callers

`journal_ui_thread_probe.py` counts appends made on the main thread while an
asyncio loop runs (the Textual thread), over the tui/agent/chat/daily/session/tools
tests. Before: 1140 appends (run stopped by `-x` after 415 tests). After
(`ab4d121`): 786 appends over 460 tests.

| action | before | after |
|---|---|---|
| provider.request | 218 | 0 |
| credentials.use | 135 | 43 |
| session.create | 197 | 163 |
| session.resume | 211 | 199 |
| workspace.files.read | 328 | 328 |

Remaining: `workspace.files.read` comes from the GUS context pack (cached per
file stamp, so one read per changed file in a real session); session writes from
sync paths (`_save_draft` on unmount/turn close, resume from the sessions tab)
stay synchronous for ordering. Both now cost ~3 ms CPU each instead of ~130 ms.
