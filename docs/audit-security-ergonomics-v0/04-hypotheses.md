# 04 — Hypotheses

**Commit:** `b76377d` · **Date:** 2026-10-15
Status: unproven. Each hypothesis needs a controlled falsification experiment before it can guide remediation.

---

## H1 · Startup async causes test flakiness

**Statement:** Test flakiness is caused by fire-and-forget background tasks during startup, not by security checks.

**Evidence so far:**
- 632 `pilot.pause()` call sites across 91 test files
- 7 background tasks during startup; 5 with `exit_on_error=True`
- CI failure observed: `test_grok_auth_tui[True]` (run 38722443292) caused by late journal write
- Fixed by moving baseline capture after modal appears (commit `b76377d`)
- No readiness state machine exists to await

**Falsification experiment:**
1. Implement a minimal readiness flag (`app.ready: bool`) set at the end of `_startup_workspace`
2. Modify 5 flaky tests to `await app.wait_for_ready()` instead of `pilot.pause()` loops
3. Run the 5 tests 50 times each
4. Measure flakiness rate before vs after

**If readiness eliminates flakiness → H1 proven. If flakiness persists → H1 refuted (flakiness has another root cause).**

**Cost:** ~2 hours implementation + ~1 hour test runs.

---

## H2 · Security dominates latency

**Statement:** The security stack (Authority + Sentinel + Journal) is the primary contributor to perceived latency in action execution.

**Evidence so far (measured):**
- `authority.evaluate`: 1.919 ms/op
- `sentinel.evaluate`: 2.027 ms/op (20.4% of full)
- `gate.authorize` (full): 9.921 ms/op
- Journal write cost: 7.894 ms/op (79.6% of full)
- Startup mount + first pause: 946-1029 ms

**Status: REFUTED.** Journal persistence dominates, not security checks. The checks are cheap; the I/O is expensive.

**Residual question:** Is the journal write actually perceived as latency, or is it invisible (happens in background)? Need user testing to determine perceived latency threshold.

---

## H3 · Dispersed state causes interference

**Statement:** State dispersed across 42 env vars and 10+ storage locations causes cross-test pollution and user-facing confusion.

**Evidence so far:**
- 4 tests must monkeypatch `HOME` to avoid real user state (`test_turn_control.py:52`, `test_egress.py:43`, `test_workspace_sessions.py:134`, `test_git_owner.py:28`)
- `state_root()` has 29 call sites across 24 files
- Split-brain: `state_root()` vs explicit `state_directory` parameters can disagree
- `ActionApprovalStore` defaults to in-memory (no persistence) — corrected from earlier assumption
- Workspace switch retains grants keyed by path hash (not by workspace identity)

**Falsification experiment:**
1. Run full test suite with `ISYCODE_STATE_HOME` unset
2. Check `~/.local/state/isycode/` for writes during test run
3. Run suite again in parallel (2 workers) and check for cross-pollution
4. Measure rate of state-related test failures

**If no pollution occurs → H3 refuted. If pollution occurs → H3 proven.**

**Cost:** ~30 minutes.

---

## H4 · Multiple inheritance causes coupling

**Statement:** The 9-mixin MRO creates bidirectional dependencies that make maintenance expensive.

**Evidence so far:**
- 7 bidirectional coupling pairs (Chat↔Session heaviest: 27+1 sites)
- Directed cycle through 6 of 9 mixins: Menu→Session→Tool→Workspace→Rail→Provider→Menu
- Cross-mixin attribute access: MenuMixin reads 68 external `self.*` names; ChatMixin 47; SessionMixin 43
- TUIApp has 118 methods

**Falsification experiment:**
1. Pick one feature change (e.g., "add a new menu entry that triggers an approval")
2. Measure how many files must be touched
3. Count cross-mixin call sites involved
4. Compare to a hypothetical implementation with explicit interfaces (e.g., Protocol classes)

**If feature change touches ≤2 files → H4 weakly proven. If >5 files → H4 strongly proven.**

**Cost:** ~1 hour (design + implement one feature two ways).

---

## H5 · Stringly-typed menus cause errors

**Statement:** The 118-entry MENU_DISPATCH dict with string method names is a source of silent bugs.

**Evidence so far:**
- 118 string→method-name entries (`tui_app_menu.py:386-505`)
- Consumed via `getattr(self, handler_name)(entry)`
- Unknown kind → silent `_blocked_notice` (no crash, no log)
- 24 distinct mode strings in `_render_menu`; 44 call sites
- No schema validation, no exhaustiveness checking

**Falsification experiment:**
1. Write a property-based test that generates random menu kinds
2. Run it against MENU_DISPATCH
3. Count silent failures (no-op, wrong layout, crash)
4. Compare to a typed alternative (Enum + exhaustive match)

**If property test finds ≥1 silent failure → H5 proven. If 0 failures → H5 refuted.**

**Cost:** ~30 minutes.

---

## H6 · (Implicit) Security checks are perceived as friction

**Statement:** Users perceive the approval modal as "too many prompts" and want fewer of them.

**Evidence so far:**
- 51/84 catalog actions are `approval_required=True`
- 20 ApprovalScreen subclasses; 32 security/consent modals
- Only 3/7 approval model elements are structural
- DECISION_CSS collapses button variants (red never appears)
- DENY and operational errors are visually indistinguishable

**Falsification experiment:**
1. User testing: observe 3 users completing a workflow that triggers 3+ approvals
2. Record time spent reading each modal
3. Ask: "Did you understand what you were authorizing?"
4. Ask: "Did any prompt feel unnecessary?"
5. Compare to Codex CLI / Claude Code approval UX

**If users report understanding each prompt → H6 refuted. If users skip reading → H6 proven.**

**Cost:** ~2 hours (user testing + synthesis).

---

## Summary

| ID | Hypothesis | Status | Next Step |
|---|---|---|---|
| H1 | Startup async → flakiness | STRONGLY SUPPORTED | Implement readiness flag, retest 5 flaky tests |
| H2 | Security dominates latency | REFUTED | N/A — journal I/O is 80% of cost |
| H3 | Dispersed state → interference | SUPPORTED | Run suite without ISYCODE_STATE_HOME, check pollution |
| H4 | Multiple inheritance → coupling | SUPPORTED | Measure files touched for one feature change |
| H5 | Stringly-typed menus → errors | SUPPORTED | Property-based test with random menu kinds |
| H6 | Approvals perceived as friction | UNTESTED | User testing (3 users, 3+ approvals each) |

**Recommended order:** H3 (cheapest) → H5 (cheapest) → H4 (medium) → H1 (requires implementation) → H6 (requires user testing).
