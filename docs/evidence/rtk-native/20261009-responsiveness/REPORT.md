# Command event-loop responsiveness — 2026-10-09

User observed the cat animation freezing during workspace_run. Source inspection found synchronous command revalidation (including native RTK rewrite subprocess) and staging copies inside async owner methods. Regression controls reproduced both calls on the event-loop thread before the repair (red log).

Move revalidation, scoped mask inspection, executable resolution and staging preparation into worker threads. Preserve fresh request comparison, approvals and sandbox semantics. Cancellation during copying waits for the copying worker and then cleans its staging before propagating cancellation; it never starts the command.

Final control exit 0: 75 passed in 20.95s. Includes command owner controls, native RTK, authority boundaries, coverage snapshot and cancelled-copy cleanup. No whole-suite result is claimed for this additional repair. CI on PR #40 is renewed by publication.

```bash
TMPDIR=/run/user/1000 '/home/danny/Development/ISyCo Git/ISyCode/.venv/bin/python' -m pytest -q tests/test_command_responsiveness.py tests/test_command_runner.py tests/test_rtk_integration.py tests/test_rtk_authority.py tests/test_action_coverage.py
```

Host observation: 14 GiB RAM, 10 GiB used, 4 GiB swap effectively full. That can independently slow operations; no processes or user data were removed. NOT_DEMONSTRATED: live user's UI after restart, all sources of synchronous UI IO, elimination of write/session-title latency or total command speedup. This repair addresses command preparation freezing, not host resource pressure.
