# Local long-session witness — 2026-10-01

The final run passed in 650.83 seconds (about 11 minutes), using Python 3.12
and Textual 1.0.0 on Linux with real Bubblewrap and libseccomp. The provider
was simulated; reads, edits, approved commands, Git diffs, saved sessions and
the action journal were real. This is not a GLM/provider authentication witness.

## Scenario and outcome

- One initial turn performed 60 owned file reads with streamed reasoning/content.
- Three app launches shared one saved session; each completed 25 read/edit/test/diff
  cycles. All 75 edits changed the expected exact fragment, all 75 sandboxed
  unittest commands executed one test with exit code 0, and all 75 diffs matched.
- Keyboard interaction approved 150 actual edit/command screens. Authority,
  Sentinel, execution owners, approval binding and journaling remained active.
- Nine deliberate partial-stream failures and nine cancellations preserved the
  completed conversation, allowing normal context compaction. No injected partial
  user turn survived in model history. Retry remained available after failures.
- Every fifth cycle checked history browsing without scroll jumps, End following
  the tail, and resizing between 100×30 and 80×24 terminals.
- Two restarts recovered session identity, tool notes and reported usage. Tool
  notes stayed bounded at 32 records. The saved usage matched the in-memory ledger.
- Fifteen summaries included automatic compaction after resume; the journal
  verified PASS at each launch boundary, ending with 7,265 records/3,622 receipts.
- There were 469 simulated provider requests. The final fixture value was 76,
  starting from 1. No real provider charges or authentication were exercised.

## Failure found and corrected

Two earlier runs stopped on the eighth short sandboxed test command with
`RuntimeError: command resource limits could not be applied`, caused by
`ProcessLookupError`. The parent applied `prlimit` after spawning; a fast child
could already have finished while the busy UI was waiting to resume. That also
left a window where the command ran before its resource limits were installed.

The trusted child bootstrap now applies hard CPU, open-file and file-size limits
before the existing process-limit/seccomp bootstrap executes the user program.
The approved timeout determines the CPU limit. Startup fails before user execution
if installing a limit fails. Existing approval and ownership checks remain in force.

A regression test deliberately waits for the child to exit before returning it to
the parent. Another checks effective limits from inside the command. The focused
command suite passed 28 tests; Python 3.10's local suite passed 812 tests, skipped 3
and deselected 11 external integration cases. The real-Bubblewrap TUI integration
test passed separately (1 test, 14 deselected). The final long run passed all 75
commands after the fix. One intermediate probe assertion was corrected to allow
the intended context compaction after resuming a full transcript.

## Performance limits of this evidence

Sampled process RSS ranged from about 112 to 232 MiB. Active widget counts grew
with each launch's displayed transcript (up to 1,462 widgets in the first launch)
and decreased when reopening the session. The headless harness also retains
references to the closed app until subsequent iterations; these RSS samples are
not a leak diagnosis or evidence of bounded memory over hours.

Cycle measurements ranged from 2.97 to 17.23 seconds and include simulated
streaming, widget settling, keyboard approvals, real tools, occasional failure
injection/resizing/compaction and garbage collection. They are not provider
latency or a controlled UI benchmark. Larger histories, transcript virtualization,
real interactive terminal performance/accessibility and multi-hour use remain
follow-up work. The user's real GLM session is separate evidence.

## Reproduce

From the repository with its development environment installed:

```bash
PYTHONPATH=. python -m pytest -q -s scripts/long_session_soak.py --tb=short
python -m pytest -q -m 'not integration' --tb=short
python -m pytest -q -m integration test_daily_tui.py --tb=short
```

The manual soak is not collected by the default suite: its filename deliberately
does not match `test_*.py`. It needs real Linux sandbox namespaces and fails if
Bubblewrap is unavailable. It uses pytest's temporary workspace, fake provider
credentials and an isolated state directory. The report defaults to
`/tmp/isycode-long-session-report.json`; `ISYCODE_SOAK_REPORT` can select another
existing directory. The recorded run's samples are in
[long-session-soak-2026-10-01.json](long-session-soak-2026-10-01.json).
