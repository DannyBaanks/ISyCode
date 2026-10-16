# 10 — Open Questions

**Commit:** `b76377d` · **Date:** 2026-10-15
Decisions requiring human validation before remediation proceeds.

---

## Q1 · Which remediation alternative?

**Question:** Should we implement Alternative A (minimal fixes), B (incremental refactor), or C (modular restructure)?

**Context:** See `06-remediation-alternatives.md`. Recommendation is B (incremental refactor) as the default. C is justified if the team plans to add a CLI or web frontend within 6 months.

**Decision needed from:** Tech lead / product owner.

**Impact:** A = ~11 hours, B = ~30 hours, C = ~60 hours. B addresses root cause; A does not. C is the largest investment but yields the cleanest architecture.

**Blocking:** Phase 8 (Protocol extraction) and Phase 9 (Mypy strict) are only in B and C. If A is chosen, those phases are skipped.

---

## Q2 · Is the vault key visibility fix (F-11) a security concern?

**Question:** Moving `_register_saved_key_reader()` before the QuickStart probe means the vault key is available earlier in startup. Does this create a security window?

**Context:** Currently, QuickStart's provider-readiness probe calls `load_provider_key` at `tui.py:737-741`, but the journalled key reader is only installed at `tui.py:810`. Two `load_provider_key` calls in the same startup return different answers. F-11 proposes moving the reader registration earlier.

**Security analysis:** The reader registration does not grant any new permissions. It only makes an existing vault-stored key visible to the QuickStart probe. The key is still subject to the same access controls (WorkspaceAuthority, Sentinel). No new bypass path is introduced.

**Decision needed from:** Security reviewer.

**Impact:** If F-11 is blocked, QuickStart will continue to show "no key" for vault-stored keys. Minor UX issue, not a security issue.

**Blocking:** Phase 1 (Quick wins) includes F-11. If blocked, ship F-12, F-02, F-06 separately.

---

## Q3 · Should approval decline be permanent or time-limited?

**Question:** Currently, `WorkspaceTrust.record_decline()` stores a decline with no expiry (permanent until user manually clears). Should declines expire after a configurable period?

**Context:** Invariant I-08 ("Decline is remembered") is preserved either way. But a permanent decline may be too aggressive — user might want to reconsider after a week.

**Options:**
- A: Keep permanent (current behavior).
- B: Time-limited (e.g., 30 days).
- C: Configurable per-workspace (user sets expiry in Settings).

**Decision needed from:** Product owner.

**Impact:** A is simplest. B requires adding expiry logic to `WorkspaceTrust`. C requires adding a Settings UI element.

**Blocking:** None. This is a product decision, not a technical blocker.

---

## Q4 · Should DENY severity be orange or a different color?

**Question:** F-07 proposes adding a `security-denied` severity with orange color. Is orange the right choice?

**Context:** Currently, DENY and operational errors both use YELLOW. The goal is to make DENY visually distinct. Orange was chosen because it is distinct from YELLOW (errors) and RED (critical), and is commonly associated with "warning" in UI design.

**Alternatives:**
- A: Orange (proposed).
- B: Purple (distinct from all existing colors).
- C: Keep yellow but add a distinct icon (e.g., 🛡️ shield icon for DENY).

**Decision needed from:** UX designer / product owner.

**Impact:** Cosmetic only. No security impact.

**Blocking:** Phase 4 (Visual taxonomy) includes F-07. If color choice is undecided, ship the icon alternative (C) as an interim measure.

---

## Q5 · Should `ActionApprovalStore` persist across sessions?

**Question:** Currently, `ActionApprovalStore` is in-memory only (no persistence). Approvals are lost when the app restarts. Should they persist?

**Context:** Invariant I-04 ("One-use digest-bound approvals") is preserved either way. But persistence would allow approvals to survive a crash or intentional restart.

**Security analysis:** Persisting approvals increases the attack surface — an attacker with filesystem access could replay approvals. However, approvals are digest-bound and TTL-limited (1-120s), so replay is unlikely. The journal already persists decisions (I-05), so persisting approvals is consistent.

**Options:**
- A: Keep in-memory (current behavior, safest).
- B: Persist with encryption (e.g., OS keyring).
- C: Persist in plaintext with TTL (simplest, least safe).

**Decision needed from:** Security reviewer.

**Impact:** A is safest. B adds complexity. C is simplest but increases risk.

**Blocking:** None. This is a security decision, not a technical blocker.

---

## Q6 · Should we add a CLI frontend?

**Question:** Alternative C (modular restructure) is justified if the team plans to add a CLI or web frontend within 6 months. Is a CLI frontend planned?

**Context:** Currently, ISyCode is TUI-only. A CLI frontend would reuse the domain core (`src/isycode/core/` and `src/isycode/domain/`) but have a different presentation layer.

**Decision needed from:** Product owner / tech lead.

**Impact:** If yes → choose Alternative C. If no → choose Alternative B.

**Blocking:** Phase 8 (Protocol extraction) and Phase 9 (Mypy strict) are only in B and C. If A is chosen, those phases are skipped.

---

## Q7 · Should we fix the 4 tests that monkeypatch `HOME`?

**Question:** Four tests (`test_turn_control.py:52`, `test_egress.py:43`, `test_workspace_sessions.py:134`, `test_git_owner.py:28`) monkeypatch `HOME` to avoid writing to the real user's `~/.local/state/isycode/`. Should we fix them to use `ISYCODE_STATE_HOME` instead?

**Context:** F-10 (dispersed state) identifies this as a symptom of the problem. The fix is to use `ISYCODE_STATE_HOME` (which the tests already set) instead of monkeypatching `HOME`.

**Decision needed from:** Tech lead.

**Impact:** Low. The monkeypatching works, but is fragile and confusing. Fixing it is a small improvement.

**Blocking:** None. This is a code quality issue, not a technical blocker.

---

## Q8 · Should we add integration tests for the full stack?

**Question:** Alternative C (modular restructure) includes C7 (integration test suite that exercises full stack: TUI → core → adapters). Should we add these tests even if we choose Alternative B?

**Context:** Currently, there are no integration tests that exercise the full stack. Unit tests cover individual components, but not their interactions. Integration tests would catch regressions that unit tests miss.

**Decision needed from:** Tech lead.

**Impact:** Integration tests add confidence but require significant investment (~8 hours for C7). If the team has capacity, they are valuable even without Alternative C.

**Blocking:** None. This is a testing strategy decision, not a technical blocker.

---

## Q9 · Should we enforce import-linter in CI?

**Question:** Alternative C (modular restructure) includes C5 (add `pyproject.toml` with explicit package boundaries; enforce with `import-linter`). Should we enforce import-linter even if we choose Alternative B?

**Context:** Import-linter prevents architectural regressions (e.g., TUI importing directly from adapters). Even without Alternative C's package reorganization, import-linter can enforce "TUI does not import from adapters" as a rule.

**Decision needed from:** Tech lead.

**Impact:** Import-linter adds a CI gate that prevents future coupling regressions. Low investment (~2 hours), high value.

**Blocking:** None. This is a code quality decision, not a technical blocker.

---

## Q10 · Should we fix the preexisting `validate_gates` sha256 warnings?

**Question:** `validate_gates` locally shows preexisting failures for sha256 M6/M7/M8/M9. These do not block CI, but they are noise. Should we fix them?

**Context:** These warnings are not related to the audit. They are preexisting technical debt. Fixing them is out of scope for this remediation but would clean up the local development experience.

**Decision needed from:** Tech lead.

**Impact:** Low. The warnings are noise but do not block CI. Fixing them is a small cleanup.

**Blocking:** None. This is a code quality issue, not a technical blocker.

---

## Summary

| ID | Question | Decision Needed From | Blocking? |
|---|---|---|---|
| Q1 | Which remediation alternative? | Tech lead / product owner | Yes — determines scope |
| Q2 | Is F-11 a security concern? | Security reviewer | Yes — Phase 1 |
| Q3 | Should decline be permanent or time-limited? | Product owner | No |
| Q4 | Should DENY severity be orange or different? | UX designer / product owner | No — Phase 4 |
| Q5 | Should ActionApprovalStore persist? | Security reviewer | No |
| Q6 | Should we add a CLI frontend? | Product owner / tech lead | Yes — determines Alternative B vs C |
| Q7 | Should we fix the 4 HOME-monkeypatching tests? | Tech lead | No |
| Q8 | Should we add integration tests? | Tech lead | No |
| Q9 | Should we enforce import-linter? | Tech lead | No |
| Q10 | Should we fix validate_gates sha256 warnings? | Tech lead | No |

**Critical path:** Q1 and Q6 determine the remediation scope. Q2 determines whether F-11 ships in Phase 1. All other questions are non-blocking.
