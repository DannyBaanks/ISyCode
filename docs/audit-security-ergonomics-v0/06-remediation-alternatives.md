# 06 — Remediation Alternatives

**Commit:** `b76377d` · **Date:** 2026-10-15
Three alternatives: A (minimal fixes), B (incremental refactor), C (modular restructure).

---

## Alternative A — Minimal Fixes

**Scope:** Fix the 12 verified findings without changing architecture. No new abstractions. No file reorganization.

### Changes

| ID | Fix | Files | Effort |
|---|---|---|---|
| F-01 | Add `app.ready: bool` + `app.wait_for_ready()` at end of `_startup_workspace` | `tui.py` | 30 min |
| F-02 | Override `exit_on_error=False` for all 7 startup workers; widen except to `Exception` | `tui.py:655, 719, 814` | 15 min |
| F-03 | Reader takes `LOCK_SH` in `verify()`; remove mtime/size check | `action_audit.py:132-161` | 30 min |
| F-04 | Tests await `app.wait_for_ready()` before capturing baselines | 5 test files | 30 min |
| F-06 | Change placeholder strings: "Starting…" → "Not started"; MCP "None configured" → "Loading…" | `tui_widgets.py:331-354`, `tui.py:2504-2506` | 15 min |
| F-07 | Add `"security-denied"` severity to theme (orange); use for DENY transcript lines | `tui_theme.py:139`, `tui_app_tools.py:299`, `tui_app_workspace.py:439` | 30 min |
| F-08 | Add structural fields to `ApprovalScreen` base: `_render_owner()`, `_render_scope()`, `_render_duration()` | `tui_screens_approval.py` | 2 hr |
| F-09 | Convert `MENU_DISPATCH` to `Enum` + exhaustive `match` | `tui_app_menu.py:386-505` | 3 hr |
| F-10 | Add `StateIndex` class that resolves all state paths; refactor 29 `state_root()` call sites | new file + 24 files | 4 hr |
| F-11 | Move `_register_saved_key_reader()` before QuickStart probe | `tui.py:737, 810` | 5 min |
| F-12 | Delete dead code in `MemoryConfirmScreen` | `tui_screens_approval.py:600-626` | 10 min |

**Total effort:** ~11 hours.

### Pros
- Smallest diff. Lowest risk of regression.
- Each fix is independent; can be shipped one-by-one.
- No architectural change → no new coupling.

### Cons
- Does not address F-05 (mixin coupling) — the root cause of maintenance friction.
- F-10 (StateIndex) is a new abstraction but only used by existing call sites.
- F-09 (Enum menus) is a large mechanical change but no behavior change.

### When to choose A
- Need to ship fixes quickly (e.g., before a demo).
- Team is small and cannot afford architectural change.
- Risk tolerance is low.

---

## Alternative B — Incremental Refactor

**Scope:** All fixes from A, plus incremental extraction of mixin responsibilities into explicit interfaces. No file reorganization beyond what extraction requires.

### Additional Changes (beyond A)

| ID | Fix | Files | Effort |
|---|---|---|---|
| F-05a | Define `Protocol` classes for cross-mixin interfaces: `SessionProvider`, `ChatController`, `WorkspaceController` | new file `tui_protocols.py` | 2 hr |
| F-05b | Extract `ChatSessionMixin` from `ChatMixin` + `SessionMixin` (chat-specific methods only) | new file `tui_app_chat_session.py` | 4 hr |
| F-05c | Extract `ApprovalMixin` from `AuthorityMixin` + `MenuMixin` (approval modal handling) | new file `tui_app_approvals.py` | 3 hr |
| F-05d | Reduce TUIApp to 6 mixins (Session, Rail, Provider, Workspace, Tool, Menu) with clear boundaries | `tui.py` | 4 hr |
| F-05e | Add mypy strict mode for mixin files; fix type errors | all mixin files | 6 hr |

**Total effort:** ~30 hours (includes A).

### Pros
- Addresses root cause of maintenance friction (F-05).
- Incremental: each extraction can be shipped independently.
- Protocols make cross-mixin dependencies explicit and testable.
- Mypy strict catches future coupling regressions.

### Cons
- Larger diff than A. Higher risk of regression.
- Requires team agreement on Protocol design before extraction.
- F-05e (mypy strict) may uncover many latent type errors.

### When to choose B
- Team plans to add significant new features to TUI.
- Team has capacity for architectural improvement.
- Risk tolerance is moderate.

---

## Alternative C — Modular Restructure

**Scope:** All fixes from B, plus full reorganization of `src/isycode/` into packages with clear boundaries. TUI becomes a thin presentation layer over a domain core.

### Additional Changes (beyond B)

| ID | Fix | Files | Effort |
|---|---|---|---|
| C1 | Create `src/isycode/core/` package: `action_runtime.py`, `workspace_authority.py`, `security.py`, `approvals.py`, `action_audit.py`, `effect_policy.py`, `workspace_trust.py` | move 7 files | 4 hr |
| C2 | Create `src/isycode/domain/` package: `action_catalog.py`, `contracts.py`, `credentials.py`, `state.py` | move 4 files | 2 hr |
| C3 | Create `src/isycode/tui/` package: `tui.py`, `tui_app_*.py`, `tui_screens_*.py`, `tui_widgets.py`, `tui_theme.py` | move ~30 files | 4 hr |
| C4 | Create `src/isycode/adapters/` package: provider adapters, LSP, git, etc. | move ~20 files | 4 hr |
| C5 | Add `pyproject.toml` with explicit package boundaries; enforce with `import-linter` | new file | 2 hr |
| C6 | Refactor TUI to depend only on `core` + `domain` (no direct adapter imports) | `tui.py` + mixins | 6 hr |
| C7 | Add integration test suite that exercises full stack (TUI → core → adapters) | new test files | 8 hr |

**Total effort:** ~60 hours (includes B).

### Pros
- Clear package boundaries prevent future coupling regressions.
- `import-linter` enforces architecture at CI time.
- TUI becomes thin → easier to reason about, easier to test.
- Domain core is framework-independent → can be reused by CLI, API, etc.

### Cons
- Largest diff. Highest risk of regression.
- Requires team agreement on package structure before migration.
- C7 (integration tests) is a significant investment.
- May uncover hidden dependencies between layers.

### When to choose C
- Team plans to add multiple frontends (CLI, API, web) over the same core.
- Team has capacity for significant architectural investment.
- Risk tolerance is high (or team has strong test coverage to catch regressions).

---

## Comparison Matrix

| Criterion | A (Minimal) | B (Incremental) | C (Modular) |
|---|---|---|---|
| Effort | ~11 hr | ~30 hr | ~60 hr |
| Risk of regression | Low | Medium | High |
| Addresses F-05 (coupling) | No | Yes | Yes |
| Addresses F-10 (state) | Yes (StateIndex) | Yes (StateIndex) | Yes (StateIndex + packages) |
| Future coupling prevention | No | mypy strict | import-linter + packages |
| Multiple frontends possible | No | No | Yes |
| Time to first fix | 15 min (F-11) | 15 min (F-11) | 15 min (F-11) |
| Team agreement required | No | Protocol design | Package structure |

---

## Recommendation

**Choose B (Incremental Refactor)** as the default path.

Rationale:
- A does not address the root cause (F-05). The team will continue to pay the coupling tax.
- C is a large investment that may not be justified if the team is small or the product is stable.
- B is the sweet spot: addresses root cause, incremental, moderate risk.
- B's Protocol extraction can be done incrementally — start with the heaviest coupling pair (Chat↔Session) and extract only that.

**Exception:** If the team plans to add a CLI or web frontend within 6 months, choose C — the package boundaries will pay for themselves.

---

## Security Invariant Preservation (all alternatives)

All three alternatives preserve the 12 security invariants (see `05-security-invariant-matrix.md`). None of the changes touch Authority, Sentinel, Owners, Grants, or the Journal's write path. The only security-adjacent change is F-03 (reader lock in `verify()`), which *strengthens* I-05 by eliminating the false JOURNAL_INVALID race.

**Verification:** Each alternative must pass the full test suite (`pytest tests/security/`) before shipping.
