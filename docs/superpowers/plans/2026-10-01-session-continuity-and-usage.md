# Session continuity and usage implementation plan

Goal: retain bounded, redacted tool activity across chat turns/restarts; install the same tested Textual version everywhere; expose provider-reported token consumption and an optional session budget.

Design: extend portable session state with validated tool history and consumption counters. Tool history is untrusted context, not executable requests, approvals, grants or raw reasoning. Existing owned state persistence binds its digest and remains the only writer. Preserve old session formats. Resume does not run tools. Use Textual 1.0.0, currently validated on Python 3.10/3.12, and reconcile README claims. Usage totals are lower bounds when provider responses omit token metadata; never invent API prices. Budget is opt-in and checked before every model request including compaction. Under a configured budget, stop on unknown usage rather than claim enforcement. Restrict answer output to remaining known budget; input and in-flight calls can exceed a token budget, so label it as stopping subsequent requests, not a billing guarantee.

Global constraints: Python >=3.10; preserve Authority/Sentinel/approval/journaling. No live provider credential reads/calls for tests; no OAuth changes. Prior auth WIP remains stashed. Base includes fd48322 ordered chat/scroll correction.

Tasks:
- [x] 1. Bounded redacted tool-history helpers and portable state validation. Fail-first tests: malicious/oversized state, secrets, old state, export/import/fork and no automatic replay.
- [x] 2. Pin Textual 1.0.0 and reconcile compatibility docs; verify import metadata and startup/navigation tests.
- [x] 3. Token ledger, malformed/missing usage, optional budget and defaults. Fail-first tests for OpenAI/Anthropic shapes, counters, budget exhaustion and unknown usage.
- [x] 4. Integrate tool context, resume display, status/usage command and Settings budget into the TUI. Full-app tests: second-turn/restart context, no tool replay, cancellation after an applied tool, budgets across tool rounds and summaries, saved counters.
- [x] 5. Reconcile roadmap, regenerate authority snapshot, independent review, full CI command on Python 3.10, commit and push feature branch.

Review focus: tool records must not grant authority; interrupted applied effects must survive as notes without partial assistant persistence; hidden reasoning never saved; missing usage is never zero; imported counters/history validated as untrusted data; old conversation versions continue loading; search/tail navigation remains usable.

## Completion evidence

All five tasks completed. Fail-first tests reproduced lost tool context, missing budgets, provider output inflation, malformed/embedded secret leaks, cache-token undercount, late effects after cancellation, cancelled compaction losing accounting, hidden budget text at 80 columns, and unreadable preferences permitting a request. Independent task and integration reviews found no remaining blockers after corrections.

- Python3.10 full CI command: 808 passed, 3 skipped, 11 external integration cases deselected. After the final compact-status/read-error adjustments, focused Python3.10 TUI/session/scroll tests: 44 passed.
- Final Python3.12 full CI command: 810 passed, 3 skipped, 11 deselected (includes the two final regressions).
- Real local Bubblewrap TUI workflow: 1 passed, 14 deselected. Provider responses simulated; real owned reads, edit, approved unittest and Git diff executed.
- Exact Textual1.0.0 imports confirmed on both versions; dependency pin and historical README claims independently reviewed.
- Optional actual Anthropic SDK test remains skipped; injected SDK and SSE tests passed. No live provider calls, OAuth login, remote integration, long-duration performance or desktop clipboard claim.
- Authority coverage regenerated and diff whitespace checks passed. Branch builds on the user's updated code plus fd48322; OAuth WIP remains preserved separately.
