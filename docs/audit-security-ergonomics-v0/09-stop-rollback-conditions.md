# 09 — Stop / Rollback Conditions

**Commit:** `b76377d` · **Date:** 2026-10-15
Conditions that mandate stopping a migration phase and rolling back.

---

## Universal Stop Conditions (any phase)

Stop immediately if ANY of the following occur:

### Security

| Condition | Severity | Action |
|---|---|---|
| Any security invariant test fails (`tests/security/`) | CRITICAL | Roll back to previous phase. Do not proceed. |
| Journal `verify()` returns JOURNAL_INVALID on a clean workspace | CRITICAL | Roll back. Investigate before retrying. |
| An action executes without passing through `authorize()` | CRITICAL | Roll back. This is a bypass path. |
| DENY is converted to ALLOW by a UI failure | CRITICAL | Roll back. This violates I-10. |
| A new code path reaches `owner.execute()` without `ProductActionGate.authorize()` | CRITICAL | Roll back. |

### Stability

| Condition | Severity | Action |
|---|---|---|
| Test suite runtime increases by >20% | HIGH | Pause. Investigate before proceeding. |
| Any test that previously passed now fails (regression) | HIGH | Fix or roll back. Do not proceed with failing tests. |
| App crashes on startup | CRITICAL | Roll back. |
| App hangs on startup (>10s) | CRITICAL | Roll back. |

### Architecture

| Condition | Severity | Action |
|---|---|---|
| Bidirectional mixin pairs increase (instead of decrease) | MEDIUM | Pause. Re-evaluate extraction strategy. |
| TUIApp method count increases (instead of decrease) | MEDIUM | Pause. Re-evaluate extraction strategy. |
| A new cyclic dependency is introduced | HIGH | Roll back. |

---

## Phase-Specific Stop Conditions

### Phase 1 — Quick wins

| Condition | Severity | Action |
|---|---|---|
| F-11 fix causes QuickStart to hang | HIGH | Revert F-11. Ship F-12, F-02, F-06 separately. |
| F-02 fix causes uncaught exceptions to be silently swallowed | MEDIUM | Narrow except back to `(ValueError, OSError, Exception)`. Add logging. |
| F-06 fix causes rail to show "Loading…" indefinitely | MEDIUM | Add timeout. Revert to previous string if timeout exceeded. |

### Phase 2 — Readiness state machine

| Condition | Severity | Action |
|---|---|---|
| `wait_for_ready()` times out (>10s) in any test | HIGH | Investigate. Do not increase timeout without root-causing. |
| Flakiness rate does not decrease after readiness | HIGH | H1 is refuted. Roll back readiness. Investigate other flakiness causes. |
| Readiness flag is set before subsystems are actually ready | HIGH | Roll back. Flag must be accurate. |

### Phase 3 — Journal reader lock

| Condition | Severity | Action |
|---|---|---|
| Journal race test ×200 shows >0% JOURNAL_INVALID | CRITICAL | Roll back. Lock is not effective. |
| `verify()` hangs under concurrent write | CRITICAL | Roll back. Deadlock risk. |
| Performance regression in `verify()` (>50% slower) | MEDIUM | Investigate. May need finer-grained locking. |

### Phase 4 — Visual taxonomy

| Condition | Severity | Action |
|---|---|---|
| New severity `security-denied` is not recognized by theme | MEDIUM | Revert. Use existing severity. |
| DENY lines still render as yellow | MEDIUM | Revert. Investigate theme resolution. |

### Phase 5 — Approval structural fields

| Condition | Severity | Action |
|---|---|---|
| Any approval modal fails to mount | CRITICAL | Roll back. Modal must render. |
| Refuse-first focus is lost | CRITICAL | Roll back. Violates I-03. |
| Structural fields cause modal to overflow screen | MEDIUM | Adjust layout. Do not remove fields. |
| 20/20 screens do not have structural fields after update | HIGH | Complete the update before merging. |

### Phase 6 — Typed menu dispatch

| Condition | Severity | Action |
|---|---|---|
| Any menu entry that previously worked now fails | HIGH | Fix or roll back. |
| `match` statement raises `ValueError` for a valid menu action | HIGH | Add missing case. |
| Property-based test finds a silent failure | HIGH | Fix the dispatch. |

### Phase 7 — StateIndex

| Condition | Severity | Action |
|---|---|---|
| StateIndex resolves a different path than previous `state_root()` | HIGH | Investigate. Paths must be identical. |
| Any test that previously passed now fails due to state resolution | HIGH | Fix StateIndex or roll back. |
| Env var leakage: StateIndex reads a var that `state_root()` did not | MEDIUM | Investigate. May be intentional or a bug. |

### Phase 8 — Protocol extraction

| Condition | Severity | Action |
|---|---|---|
| Bidirectional pairs do not decrease | MEDIUM | Re-evaluate extraction. May need different boundaries. |
| A new cyclic dependency is introduced | HIGH | Roll back. |
| Chat or approval functionality breaks | CRITICAL | Roll back. |
| TUIApp method count does not decrease | MEDIUM | Re-evaluate extraction. |

### Phase 9 — Mypy strict

| Condition | Severity | Action |
|---|---|---|
| >100 type errors across 9 mixin files | MEDIUM | Fix incrementally. Do not enable strict for all files at once. |
| Mypy strict uncovers a latent bug | HIGH | Fix the bug. Do not suppress the type error. |

### Phase 10 — Final verification

| Condition | Severity | Action |
|---|---|---|
| Any test fails | CRITICAL | Roll back to Phase 9. |
| Any security invariant test fails | CRITICAL | Roll back to Phase 9. |
| Journal hash chain does not match Phase 0 | CRITICAL | Investigate. May indicate tampering or a bug. |
| Performance metrics regress by >20% | MEDIUM | Investigate before merging. |

---

## Rollback Procedure

1. **Identify the last working phase.** Each phase ends with a commit. The last commit that passed all tests is the rollback target.

2. **Roll back to that commit.**
   ```bash
   git reset --hard <last-working-commit>
   ```

3. **Verify rollback.**
   ```bash
   pytest tests/ -q
   pytest tests/security/ -q
   ```

4. **Do NOT roll back across a phase that shipped a security fix** (Phase 3, 4, 5). Those fixes must be preserved even if later phases fail. If a later phase fails, cherry-pick the security fixes onto the rolled-back branch.

5. **Document the failure.** Add a note to `CHANGELOG.md` explaining what failed and why.

6. **Investigate before retrying.** Do not retry the same phase without root-causing the failure.

---

## Escalation

If a CRITICAL condition occurs and the rollback target is unclear:

1. Stop all work.
2. Notify the team.
3. Do not attempt to fix forward.
4. Roll back to the baseline commit (`b76377d`) if no other target is clear.
5. Re-run the full test suite to confirm clean state.

---

## Summary

**Never proceed past a failing security invariant test.**
**Never roll back across a shipped security fix.**
**Always root-cause before retrying.**
