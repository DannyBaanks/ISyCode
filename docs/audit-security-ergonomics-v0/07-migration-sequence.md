# 07 — Migration Sequence

**Commit:** `b76377d` · **Date:** 2026-10-15
Recommended phased migration for Alternative B (Incremental Refactor).

---

## Phase 0 — Pre-flight (before any code changes)

**Duration:** 1 hour
**Goal:** Establish baseline and safety net.

### Tasks

1. **Capture baseline metrics**
   - Test suite runtime: `time pytest tests/ -q` (expect ~3-5 min)
   - Test pass rate: `1977 passed, 3 skipped, 11 deselected`
   - Startup latency: 3 cold runs, record mount + first pause
   - Authorization latency: 500 iterations, record authority/sentinel/journal
   - Cross-mixin coupling: count bidirectional pairs (expect 7)
   - TUIApp method count: `grep -c "def " tui.py` (expect 118)

2. **Create feature branch**
   - `git checkout -b refactor/incremental-v0`
   - All subsequent work on this branch.

3. **Add CI gate for security invariants**
   - Add `pytest tests/security/ -q` as a separate CI job.
   - This job must pass before any merge.

4. **Record current journal hash chain**
   - Run `journal.verify()` on a test workspace.
   - Save the chain hash as a reference for post-migration comparison.

**Exit criteria:** Baseline recorded, branch created, CI gate added.

---

## Phase 1 — Quick wins (F-11, F-12, F-02, F-06)

**Duration:** 1 hour
**Goal:** Ship low-risk fixes that improve UX and stability without architectural change.

### Tasks

1. **F-11: Move `_register_saved_key_reader()` before QuickStart probe**
   - Edit `tui.py`: move line 810 to before line 737.
   - Test: fresh non-recurring workspace with vault-stored key → QuickStart shows "key found".

2. **F-12: Delete dead code in `MemoryConfirmScreen`**
   - Edit `tui_screens_approval.py`: delete lines 600-626 (duplicated `__init__/compose/on_mount/on_button_pressed`).
   - Test: `pytest tests/screens/test_memory_confirm.py` → pass.

3. **F-02: Override `exit_on_error=False` for startup workers**
   - Edit `tui.py`: change lines 655, 719, 814 to `run_worker(..., exit_on_error=False)`.
   - Widen except in `_check_gateway_async` and `_load_sentinel_journal` to `Exception`.
   - Test: mock a non-OSError in `_check_gateway_async` → app does not exit.

4. **F-06: Fix lying placeholders**
   - Edit `tui_widgets.py:331-354`: change "Starting local mobile host…" → "Not started".
   - Edit `tui.py:2504-2506`: change MCP "None configured" → "Loading…" when `snapshot.state != "ready"`.
   - Test: mount TUI, read rail before interaction → no misleading strings.

**Exit criteria:** 4 fixes shipped, all tests pass, no architectural change.

---

## Phase 2 — Readiness state machine (F-01, F-04)

**Duration:** 3 hours
**Goal:** Eliminate test flakiness caused by fire-and-forget startup.

### Tasks

1. **F-01: Add readiness flag**
   - Edit `tui.py`: add `self._ready = False` in `__init__`.
   - Add `self._ready_event = asyncio.Event()` in `__init__`.
   - At end of `_startup_workspace`: `self._ready = True; self._ready_event.set()`.
   - Add `async def wait_for_ready(self, timeout=10.0)`: `await asyncio.wait_for(self._ready_event.wait(), timeout)`.
   - Add property `ready: bool`.

2. **F-04: Update 5 flaky tests to await readiness**
   - `test_grok_auth_tui.py`: replace `pilot.pause()` loops with `await app.wait_for_ready()`.
   - `test_continuity_recovery.py:186-193`: replace `app.workers` polling with `await app.wait_for_ready()`.
   - `test_workspace_mode.py`: same.
   - `test_quickstart.py`: same.
   - `test_sentinel_rail.py`: same.

3. **Run flakiness measurement**
   - Execute the 5 tests 50 times each.
   - Record pass/fail rate.
   - Compare to baseline (expect: flakiness drops to 0%).

**Exit criteria:** Readiness flag added, 5 tests updated, flakiness measured.

---

## Phase 3 — Journal reader lock (F-03)

**Duration:** 1 hour
**Goal:** Eliminate false JOURNAL_INVALID under concurrent write.

### Tasks

1. **F-03: Reader takes `LOCK_SH` in `verify()`**
   - Edit `action_audit.py:132-161`: replace mtime/size check with `fcntl.flock(f, fcntl.LOCK_SH)`.
   - Remove the `if size != initial_size or mtime != initial_mtime: raise ValueError(...)` block.
   - Keep the chain walk logic unchanged.

2. **Run race reproduction**
   - Execute the 200-attempt concurrent verify test.
   - Record JOURNAL_INVALID rate (expect: 0%).

3. **Update security invariant test**
   - Edit `tests/security/test_journal_hash_chain.py`: add a concurrent write test.
   - Assert `verify()` returns PASS under concurrent write.

**Exit criteria:** Reader lock added, race eliminated, security test updated.

---

## Phase 4 — Visual taxonomy (F-07)

**Duration:** 1 hour
**Goal:** Make DENY visually distinct from operational errors.

### Tasks

1. **F-07: Add `security-denied` severity**
   - Edit `tui_theme.py:139`: add `"security-denied": "orange"` to severity map.
   - Edit `tui_app_tools.py:299`: change DENY transcript line from `("✗ ", ..., "yellow")` to `("✗ ", ..., "security-denied")`.
   - Edit `tui_app_workspace.py:439`: same change.

2. **Add test**
   - New test: `tests/theme/test_security_denied_severity.py`.
   - Assert `_semantic_box_title("security-denied")` returns "DENIED".
   - Assert `notify_semantic("security-denied")` uses orange color.

**Exit criteria:** New severity added, DENY lines use orange, test passes.

---

## Phase 5 — Approval model structural fields (F-08)

**Duration:** 4 hours
**Goal:** Ensure all approval modals state OWNER, SCOPE, DURATION explicitly.

### Tasks

1. **F-08: Add structural fields to `ApprovalScreen` base**
   - Edit `tui_screens_approval.py`: add `_render_owner(owner: str) -> Static` method.
   - Add `_render_scope(scope: str) -> Static` method.
   - Add `_render_duration(duration: str) -> Static` method.
   - Add `_render_not_granted(not_granted: list[str]) -> Static` method.

2. **Update 10 thin approval screens**
   - For each of the 10 screens that lack structural fields:
     - Call `_render_owner(...)`, `_render_scope(...)`, `_render_duration(...)` in `compose()`.
     - Add "not granted" language to body.

3. **Update DECISION_CSS**
   - Edit `tui_screens_approval.py:32`: remove `variant="error"` collapse.
   - Ensure refuse button renders red.

4. **Run acceptance test**
   - New test: `tests/screens/test_approval_structural_fields.py`.
   - Mount each of the 20 ApprovalScreen subclasses.
   - Assert each has owner, scope, duration, not-granted text.

**Exit criteria:** Structural fields added, 10 screens updated, CSS fixed, test passes.

---

## Phase 6 — Typed menu dispatch (F-09)

**Duration:** 4 hours
**Goal:** Convert stringly-typed MENU_DISPATCH to Enum + exhaustive match.

### Tasks

1. **F-09: Define `MenuAction` Enum**
   - Edit `tui_app_menu.py`: add `class MenuAction(Enum)` with 118 members.
   - Each member maps to a method name string.

2. **Convert `MENU_DISPATCH` to `Dict[MenuAction, str]`**
   - Replace string keys with `MenuAction` enum members.
   - Keep method name strings as values.

3. **Convert `_select_menu_entry` to exhaustive `match`**
   - Replace `getattr(self, handler_name)(entry)` with `match action: case MenuAction.X: self._handle_x(entry)`.
   - Add `case _: raise ValueError(f"unhandled menu action: {action}")` at end.

4. **Add mypy strict for `tui_app_menu.py`**
   - Add `# mypy: strict` at top of file.
   - Fix type errors.

5. **Run property-based test**
   - New test: `tests/menu/test_menu_dispatch_exhaustive.py`.
   - For each `MenuAction` member, assert handler method exists.
   - For 100 random menu entries, assert no silent failure.

**Exit criteria:** Enum added, dispatch converted, mypy strict, property test passes.

---

## Phase 7 — StateIndex (F-10)

**Duration:** 5 hours
**Goal:** Centralize state path resolution.

### Tasks

1. **F-10: Add `StateIndex` class**
   - New file: `src/isycode/state_index.py`.
   - Class `StateIndex` with methods:
     - `state_root() -> Path`
     - `config_root() -> Path`
     - `workspace_state(workspace_root: Path) -> Path`
     - `journal_path(workspace_root: Path) -> Path`
     - `trust_path(workspace_root: Path) -> Path`
     - `approvals_path(workspace_root: Path) -> Path`
   - Singleton accessor: `get_state_index() -> StateIndex`.

2. **Refactor 29 `state_root()` call sites**
   - Replace `from isycode.state import state_root` with `from isycode.state_index import get_state_index`.
   - Replace `state_root()` with `get_state_index().state_root()`.
   - Files: 24 files (see `grep -rl "state_root" src/isycode/`).

3. **Add test**
   - New test: `tests/state/test_state_index.py`.
   - Assert `StateIndex` resolves correct paths for temp workspace.
   - Assert no env var leakage.

**Exit criteria:** StateIndex added, 29 call sites refactored, test passes.

---

## Phase 8 — Protocol extraction (F-05)

**Duration:** 10 hours
**Goal:** Reduce bidirectional coupling between mixins.

### Tasks

1. **F-05a: Define Protocol classes**
   - New file: `src/isycode/tui_protocols.py`.
   - `SessionProvider` Protocol: methods needed by ChatMixin from SessionMixin.
   - `ChatController` Protocol: methods needed by SessionMixin from ChatMixin.
   - `WorkspaceController` Protocol: methods needed by RailMixin from WorkspaceMixin.

2. **F-05b: Extract `ChatSessionMixin`**
   - New file: `src/isycode/tui_app_chat_session.py`.
   - Move chat-specific methods from `ChatMixin` and `SessionMixin`.
   - Update TUIApp MRO to include `ChatSessionMixin`.

3. **F-05c: Extract `ApprovalMixin`**
   - New file: `src/isycode/tui_app_approvals.py`.
   - Move approval modal handling from `AuthorityMixin` and `MenuMixin`.
   - Update TUIApp MRO.

4. **F-05d: Reduce TUIApp to 6 mixins**
   - After extraction, TUIApp should have: Session, Rail, Provider, Workspace, Tool, Menu.
   - ChatSession and Approval are separate mixins.

5. **Measure coupling**
   - Re-run bidirectional pair count (expect: ≤3 pairs).
   - Re-run TUIApp method count (expect: ≤80 methods).

**Exit criteria:** Protocols added, 2 mixins extracted, coupling reduced.

---

## Phase 9 — Mypy strict for all mixins (F-05e)

**Duration:** 6 hours
**Goal:** Enforce type safety for future coupling regressions.

### Tasks

1. **F-05e: Add `# mypy: strict` to all mixin files**
   - Files: `tui_app_sessions.py`, `tui_app_rail.py`, `tui_app_providers.py`, `tui_app_authority.py`, `tui_app_remote.py`, `tui_app_workspace.py`, `tui_app_tools.py`, `tui_app_chat.py`, `tui_app_menu.py`.
   - Fix type errors (expect: 50-100 errors across 9 files).

2. **Add mypy CI gate**
   - Add `mypy src/isycode/tui_app_*.py --strict` as CI job.

**Exit criteria:** All mixin files pass mypy strict, CI gate added.

---

## Phase 10 — Final verification

**Duration:** 2 hours
**Goal:** Confirm all fixes shipped, all invariants preserved.

### Tasks

1. **Run full test suite**
   - `pytest tests/ -q` → expect `1977 passed, 3 skipped, 11 deselected` (or more if new tests added).

2. **Run security invariant tests**
   - `pytest tests/security/ -q` → expect all pass.

3. **Re-measure baseline metrics**
   - Startup latency: 3 cold runs.
   - Authorization latency: 500 iterations.
   - Cross-mixin coupling: bidirectional pair count.
   - TUIApp method count.
   - Compare to Phase 0 baseline.

4. **Journal hash chain comparison**
   - Run `journal.verify()` on same test workspace as Phase 0.
   - Assert chain hash matches (no tampering).

5. **Update docs**
   - Update `CHANGELOG.md` with all fixes.
   - Update `AGENTS.md` if any contracts changed.

6. **Merge to main**
   - `git checkout main && git merge refactor/incremental-v0`.
   - Push to remote.

**Exit criteria:** All tests pass, metrics improved, docs updated, merged to main.

---

## Total Duration

| Phase | Duration | Cumulative |
|---|---|---|
| Phase 0 — Pre-flight | 1 hr | 1 hr |
| Phase 1 — Quick wins | 1 hr | 2 hr |
| Phase 2 — Readiness | 3 hr | 5 hr |
| Phase 3 — Journal lock | 1 hr | 6 hr |
| Phase 4 — Visual taxonomy | 1 hr | 7 hr |
| Phase 5 — Approval fields | 4 hr | 11 hr |
| Phase 6 — Typed menus | 4 hr | 15 hr |
| Phase 7 — StateIndex | 5 hr | 20 hr |
| Phase 8 — Protocol extraction | 10 hr | 30 hr |
| Phase 9 — Mypy strict | 6 hr | 36 hr |
| Phase 10 — Final verification | 2 hr | 38 hr |

**Total: ~38 hours (5 working days).**

---

## Rollback Points

Each phase ends with a working state. If a phase fails, roll back to the previous phase's commit.

| Phase | Rollback Target |
|---|---|
| Phase 1 fails | `git reset --hard <baseline-commit>` |
| Phase 2 fails | `git reset --hard <phase-1-commit>` |
| Phase 3 fails | `git reset --hard <phase-2-commit>` |
| ... | ... |
| Phase 10 fails | `git reset --hard <phase-9-commit>` |

**Never roll back across a phase that shipped a security fix** (Phase 3, 4, 5). Those must be preserved even if later phases fail.
