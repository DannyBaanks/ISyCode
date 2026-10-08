# G9-04 validation correction — 2026-10-08

Baseline source: 87f9fe1. Scope: scripts/soak_g9.py, validation tests and human guide.
Older untracked M9 evidence and live_g9_06.py were preserved; the old running
worker was not interrupted. No M9 approval or live-provider result is claimed.

The old cycle ignored the outcome of writer.apply(undo, None): normal owner
policy denies undo without approval. It did not verify written bytes or journal,
used ru_maxrss (peak) as final RSS and searched for a nonexistent child marker.

Now each cycle checks actual file content, observed write tool result, authorized
undo outcome/receipt, restored content and journal.verify().status. Approval is
simulated only for the exact fixture's restore request through the existing gate.
The fixture starts with an existing note so undo restores it rather than deleting
an artifact. CWD/environment patches are restored even on exceptions.

RSS comes from /proc/self/statm; warm baseline is measured after ten cycles in each
worker. Orphan check inspects actual surviving process descendants after unmount.
Final gate evaluates active duration >=7200s, >=100 cycles, exactly three restarts,
no failed checks, no descendants, verified effects and final RSS <=warm+25%, <=500MiB.
State is versioned, unique per output, bound to the script SHA256 and refuses
legacy/corrupt state. Restarts only hand off; they do not publish final output.
Child stderr is retained rather than discarded. The provider remains simulated.

Commands/results:
- .venv/bin/python -m pytest -q tests/test_soak_g9_validation.py tests/test_workspace_write.py tests/test_m9_adversarial.py
  50 passed, exit0 (regressions.log).
- G9_SOAK_SECONDS=2 .venv/bin/python scripts/soak_g9.py /tmp/isycode-g9-v2-diagnostic-20261008-01.json
  3 verified cycles, no cycle errors, status FAIL, exit1: required duration/cycles/
  restarts and warm baseline not met (diagnostic.json). A short diagnostic is
  deliberately incapable of granting G9-04 PASS.
- git diff --check: exit0.

Full corrected two-hour gate: NOT_DEMONSTRATED at this commit; separate live run
will establish its own final result. Full repository suite NOT_RUN for this script
correction. No external network/provider call is used by this soak.
