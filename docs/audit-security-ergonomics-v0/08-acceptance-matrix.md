# 08 — Acceptance Matrix

**Commit:** `b76377d` · **Date:** 2026-10-15
Tests that must pass before and after each migration phase.

---

## Functional Tests

| Test | Baseline | Post-Migration | Notes |
|---|---|---|---|
| `pytest tests/ -q` | 1977 passed, 3 skipped, 11 deselected | ≥1977 passed, ≤3 skipped, ≤11 deselected | Full suite |
| `pytest tests/security/ -q` | All pass | All pass | Security invariants |
| `pytest tests/tui/ -q` | All pass | All pass | TUI layer |
| `pytest tests/screens/ -q` | All pass | All pass | Screen rendering |
| `pytest tests/menu/ -q` | All pass | All pass | Menu dispatch |
| `pytest tests/state/ -q` | All pass | All pass | State resolution |
| `pytest tests/theme/ -q` | All pass | All pass | Visual taxonomy |

---

## Security Invariant Tests

| Invariant | Test | Must Pass |
|---|---|---|
| I-01 Deny by default | `tests/security/test_authority_deny_by_default.py` | Yes |
| I-02 No unsandboxed fallback | `tests/security/test_no_unsandboxed_fallback.py` | Yes |
| I-03 Refuse-first focus | `tests/security/test_refuse_first_focus.py` | Yes |
| I-04 One-use approvals | `tests/security/test_one_use_approvals.py` | Yes |
| I-05 Hash-chained journal | `tests/security/test_journal_hash_chain.py` | Yes |
| I-06 Effect classification | `tests/security/test_effect_classification.py` | Yes |
| I-07 Scope negation | `tests/security/test_scope_negation.py` | Yes (partial: 2/20 screens) |
| I-08 Decline remembered | `tests/security/test_decline_remembered.py` | Yes |
| I-09 Anti-drift refusal | `tests/security/test_anti_drift.py` | Yes |
| I-10 DENY never ALLOW | `tests/security/test_deny_on_ui_failure.py` | Yes |
| I-11 Visual state no permissions | `tests/security/test_visual_state_no_permissions.py` | Yes |
| I-12 Workspace boundaries | `tests/security/test_workspace_boundaries.py` | Yes |

---

## Performance Tests

| Metric | Baseline | Target | Measurement Method |
|---|---|---|---|
| Startup latency (mount + first pause) | 946-1029 ms | ≤1200 ms | 3 cold runs, median |
| Authorization latency (full) | 9.921 ms/op | ≤12 ms/op | 500 iterations, isolated temp state |
| Authority evaluate | 1.919 ms/op | ≤3 ms/op | 500 iterations |
| Sentinel evaluate | 2.027 ms/op | ≤3 ms/op | 500 iterations |
| Journal write (diff) | 7.894 ms/op | ≤9 ms/op | 500 iterations |
| Test suite runtime | ~3-5 min | ≤6 min | `time pytest tests/ -q` |

---

## UX Tests

| Test | Baseline | Post-Migration | Notes |
|---|---|---|---|
| Rail placeholders honest | "Starting local mobile host…" | "Not started" | F-06 |
| MCP column honest | "None configured" during load | "Loading…" during load | F-06 |
| DENY visually distinct | Same yellow as errors | Orange (`security-denied`) | F-07 |
| Approval modals have OWNER | 1/20 screens | 20/20 screens | F-08 |
| Approval modals have SCOPE | 0/20 screens | 20/20 screens | F-08 |
| Approval modals have DURATION | 0/20 screens | 20/20 screens | F-08 |
| Approval modals say "not granted" | 2/20 screens | 20/20 screens | F-08 |
| Refuse button is red | Collapsed to yellow | Red | F-08 |
| QuickStart sees vault key | No (reader registered late) | Yes | F-11 |

---

## Coupling Tests

| Metric | Baseline | Target | Measurement Method |
|---|---|---|---|
| Bidirectional mixin pairs | 7 | ≤3 | AST analysis |
| Directed cycle length | 6 mixins | ≤3 mixins | AST analysis |
| TUIApp method count | 118 | ≤80 | `grep -c "def " tui.py` |
| Cross-mixin attribute access (MenuMixin) | 68 external `self.*` | ≤30 | AST analysis |
| Cross-mixin attribute access (ChatMixin) | 47 external `self.*` | ≤20 | AST analysis |
| Cross-mixin attribute access (SessionMixin) | 43 external `self.*` | ≤20 | AST analysis |

---

## Type Safety Tests

| Test | Baseline | Post-Migration | Notes |
|---|---|---|---|
| `mypy src/isycode/tui_app_*.py --strict` | Not run | All pass | F-05e |
| `mypy src/isycode/state_index.py --strict` | N/A (new file) | All pass | F-10 |
| `mypy src/isycode/tui_protocols.py --strict` | N/A (new file) | All pass | F-05a |

---

## Flakiness Tests

| Test | Baseline | Post-Migration | Measurement Method |
|---|---|---|---|
| `test_grok_auth_tui[True]` ×50 | Some failures (race) | 0 failures | 50 consecutive runs |
| `test_continuity_recovery` ×50 | Some failures (race) | 0 failures | 50 consecutive runs |
| `test_workspace_mode` ×50 | Some failures (race) | 0 failures | 50 consecutive runs |
| `test_quickstart` ×50 | Some failures (race) | 0 failures | 50 consecutive runs |
| `test_sentinel_rail` ×50 | Some failures (race) | 0 failures | 50 consecutive runs |

---

## Journal Integrity Tests

| Test | Baseline | Post-Migration | Notes |
|---|---|---|---|
| `journal.verify()` under concurrent write (200 attempts) | 30% JOURNAL_INVALID | 0% JOURNAL_INVALID | F-03 |
| `journal.verify()` chain hash matches Phase 0 | Matches | Matches | No tampering |
| `journal.verify()` after 100 actions | PASS | PASS | End-to-end |

---

## Regression Tests (must not break)

| Test | Baseline | Post-Migration | Notes |
|---|---|---|---|
| `pytest tests/integration/ -q` | All pass | All pass | Full stack |
| `pytest tests/e2e/ -q` | All pass | All pass | End-to-end |
| `validate_gates` (CI) | Pass (with preexisting M6/M7/M8/M9 sha256 warnings) | Pass | Gates |
| Lint (`ruff check .`) | Pass | Pass | Code quality |
| Format (`ruff format --check .`) | Pass | Pass | Formatting |

---

## Phase-Specific Acceptance

| Phase | Must Pass Before Merge |
|---|---|
| Phase 1 (Quick wins) | `pytest tests/ -q` + `pytest tests/security/ -q` |
| Phase 2 (Readiness) | Phase 1 tests + flakiness tests ×50 |
| Phase 3 (Journal lock) | Phase 2 tests + journal race test ×200 |
| Phase 4 (Visual taxonomy) | Phase 3 tests + theme tests |
| Phase 5 (Approval fields) | Phase 4 tests + approval structural fields test |
| Phase 6 (Typed menus) | Phase 5 tests + menu dispatch exhaustive test |
| Phase 7 (StateIndex) | Phase 6 tests + state index tests |
| Phase 8 (Protocol extraction) | Phase 7 tests + coupling metrics (≤3 pairs) |
| Phase 9 (Mypy strict) | Phase 8 tests + mypy strict |
| Phase 10 (Final) | All tests + all metrics + docs updated |

---

## Summary

**Minimum acceptance criteria for any merge:**
1. `pytest tests/ -q` passes (≥1977 passed).
2. `pytest tests/security/ -q` passes (all 12 invariants).
3. `validate_gates` passes in CI.
4. Lint and format pass.

**Additional criteria for Phase 3 (security fix):**
5. Journal race test ×200: 0% JOURNAL_INVALID.

**Additional criteria for Phase 5 (security UX fix):**
6. Approval structural fields test: 20/20 screens have OWNER, SCOPE, DURATION, not-granted.

**Additional criteria for Phase 8 (coupling fix):**
7. Bidirectional mixin pairs ≤3.
8. TUIApp method count ≤80.
