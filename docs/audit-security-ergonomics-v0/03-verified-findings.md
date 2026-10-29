# 03 — Verified Findings

**Commit:** `b76377d` · **Date:** 2026-10-15
All findings verified by direct inspection or reproduction. Line numbers exact.

---

## F-01 · No readiness state machine

**Severity:** HIGH
**Evidence:** `grep -r "_ready\|is_ready\|startup_complete\|boot\|initializing\|degraded" src/isycode/` → no app lifecycle state. Only per-catalog `CatalogSnapshot.state` (`contracts.py:18-22`) and per-screen `asyncio.Event.ready`.
**Reproduction:** Mount TUIApp, interact immediately — no code path blocks on subsystem readiness.
**Impact:** Tests must poll with `pilot.pause()` (632 call sites). Two rail placeholders lie: `#mobile-host-status` = "Starting local mobile host…" (never started at startup, `tui_widgets.py:331-354`); MCP column shows "None configured" while `snapshot.state != "ready"` (`tui.py:2534-2537, 2504-2506`).
**Root cause:** UI was designed to be interactive-first; readiness was never modeled.
**Confidence:** HIGH — absence verified by exhaustive grep.

---

## F-02 · Fire-and-forget startup tasks with exit_on_error=True

**Severity:** HIGH
**Evidence:** 7 background tasks spawned during startup. 5 use Textual's default `exit_on_error=True` (`textual/dom.py:496-504`). `_check_gateway_async` (`tui.py:814`) and `_load_sentinel_journal` (`tui.py:655`) catch only `(ValueError, OSError)` — any other exception exits the app.
**Reproduction:** Raise a non-OSError in `_check_gateway_async` → app exits.
**Impact:** A transient gateway error with an unexpected exception type kills the entire TUI.
**Root cause:** `run_worker` default not overridden; narrow except clauses.
**Confidence:** HIGH — verified in Textual source and ISyCode call sites.

---

## F-03 · Journal verify-under-write race → false JOURNAL_INVALID

**Severity:** HIGH
**Evidence:** `_load_sentinel_journal` runs `journal.verify()` in an OS thread (`tui_app_rail.py:292`) while `_startup_workspace` concurrently appends via `record_decision` (`action_runtime.py:1896`). Reader takes no lock (`action_audit.py:132-161`); detects change by size/mtime/ctime comparison → raises `ValueError("journal changed during verification")` → `JOURNAL_INVALID`.
**Reproduction:** 200 verify() calls under concurrent writer thread → 60 JOURNAL_INVALID (30% rate). Measured on this machine.
**Impact:** Rail paints "JOURNAL_INVALID · 0 records" transiently. Nothing re-verifies (`_load_sentinel_journal` has one caller; the 5s timer only repaints the cached feed).
**Root cause:** Reader uses optimistic concurrency (mtime check) instead of shared lock. Writers hold `LOCK_EX` (`action_audit.py:446-448`); reader does not hold `LOCK_SH`.
**Confidence:** HIGH — reproduced at 30% rate.

---

## F-04 · Late startup journal writes pollute test baselines

**Severity:** MEDIUM
**Evidence:** Startup writes 1 decision + 1 receipt (`_load_directory` → `workspace.files.list`), plus decisions from `_check_gateway_async`, `_refresh_openisy`, `_check_model`. All fire-and-forget after UI is interactive. Tests capture baselines with `ActionAuditJournal(project).verify()` before these complete.
**Reproduction:** `test_grok_auth_tui[True]` failed in CI (run 38722443292) with `report.receipts == 1` vs `baseline.receipts == 0` on the cancel path. Fixed by moving baseline capture after modal is up (commit `b76377d`).
**Impact:** Flaky tests. Any test that asserts journal state after startup is race-prone.
**Root cause:** No readiness signal; tests cannot await startup completion.
**Confidence:** HIGH — CI failure observed and root-caused.

---

## F-05 · Bidirectional mixin coupling + 6-mixin directed cycle

**Severity:** MEDIUM
**Evidence:** 7 bidirectional pairs (Chat↔Session heaviest: 27+1 sites). Directed cycle: Menu→Session→Tool→Workspace→Rail→Provider→Menu. Cross-mixin attribute access: MenuMixin reads 68 external `self.*` names; ChatMixin 47; SessionMixin 43.
**Reproduction:** Static analysis of method call graph.
**Impact:** Every feature change is a cross-cutting concern. Hard to reason about ownership. Hard to test in isolation.
**Root cause:** Mixins were extracted from a monolith without defining clear interface boundaries. No protocol/ABC contracts between mixins.
**Confidence:** HIGH — verified by AST analysis.

---

## F-06 · Rail placeholders lie to the user

**Severity:** MEDIUM
**Evidence:** `#mobile-host-status` = "Starting local mobile host…" (`tui_widgets.py:331-354`) but mobile host is never started at startup — only from Settings menu (`tui_app_menu.py:812,907`). String only overwritten by `_refresh_mobile_host_status` called from `_start_mobile_host`. MCP column shows "− None configured" while `snapshot.state != "ready"` (`tui.py:2534-2537, 2504-2506`) — indistinguishable from genuinely having no MCP servers.
**Reproduction:** Mount TUI, read rail before any interaction.
**Impact:** User cannot distinguish "not loaded yet" from "not configured". Undermines trust in the security posture display.
**Root cause:** Placeholders written at compose time; no readiness state to gate them.
**Confidence:** HIGH — verified in source.

---

## F-07 · DENY and operational errors are visually indistinguishable

**Severity:** MEDIUM
**Evidence:** `_semantic_box_title` (`tui_theme.py:139`): both "denied" and "failed" map to RED. `notify_semantic` (`tui.py:1052-1060`): `"denied"` and `"error"` both get `("× ", ..., "error", 5.5)` — identical severity and duration. Transcript lines for DENY use YELLOW (`tui_app_tools.py:299`, `tui_app_workspace.py:439`); operational errors also use YELLOW. Only marker is the literal word ("DENY"/"denied"/"✗" vs "failed").
**Reproduction:** Trigger a DENY and an operational error — same visual treatment.
**Impact:** User cannot quickly distinguish "your security policy blocked this" from "the provider is down". Affects trust and debugging.
**Root cause:** No visual taxonomy for security decisions vs operational failures.
**Confidence:** HIGH — verified in theme and notification code.

---

## F-08 · Approval model coverage is uneven

**Severity:** MEDIUM
**Evidence:** 20 ApprovalScreen subclasses. Against the 7-element model (ACTION, OWNER, TARGET, EFFECT, SCOPE, DURATION, DECISION):
- Structural (always present): DECISION (refuse-first focus), plus ACTION/TARGET/EFFECT as free prose from callers
- Never structural: OWNER, SCOPE, DURATION — no fields; caller omission is silent
- Distribution bimodal: ~10 instances specification-grade, ~6 are two-sentence blurbs
- Only `ContextAccessScreen:142` states OWNER ("The agent started this request.")
- `DECISION_CSS:32` collapses button variants: `variant="error"` renders identically to `variant="warning"` and `variant="primary"` — red never appears on consent buttons
**Reproduction:** Inspect `tui_screens_approval.py` and 27 TailscaleConfirmScreen call sites.
**Impact:** User may not understand what they're authorizing on thin instances. "Delete conversation · y" renders same color as "Send this text · y".
**Root cause:** Template lacks structural fields for OWNER/SCOPE/DURATION. CSS collapses variants.
**Confidence:** HIGH — verified by source inspection.

---

## F-09 · Stringly-typed menu dispatch

**Severity:** LOW
**Evidence:** `MENU_DISPATCH` dict: 118 string→method-name entries (`tui_app_menu.py:386-505`). Consumed via `getattr(self, handler_name)(entry)`. Unknown kind → silent `_blocked_notice`. `_render_menu` first arg: 24 distinct static mode strings, 44 call sites. No schema validation, no exhaustiveness checking.
**Reproduction:** Pass a typo'd mode string → silent no-op or wrong layout.
**Impact:** Typos silently disable features. No compile-time or test-time detection.
**Root cause:** Dispatch designed as data table before typed registries were considered.
**Confidence:** HIGH — verified by inventory.

---

## F-10 · Dispersed state with no single resolver

**Severity:** LOW
**Evidence:** 42 env vars, 105 read sites. `state_root()` has 29 call sites across 24 files. 4 tests monkeypatch `HOME` (`test_turn_control.py:52`, `test_egress.py:43`, `test_workspace_sessions.py:134`, `test_git_owner.py:28`). `ActionApprovalStore` defaults to in-memory (no persistence) — corrected from earlier assumption. Split-brain: `state_root()` vs explicit `state_directory` parameters can disagree.
**Reproduction:** Run tests without `ISYCODE_STATE_HOME` → writes to real `~/.local/state/isycode/`.
**Impact:** Test pollution risk. Hard to reason about what state exists where. Workspace switch can retain grants keyed by path hash.
**Root cause:** State roots accumulated organically; no single authority.
**Confidence:** HIGH — verified by inventory.

---

## F-11 · Startup ordering inconsistency: vault key invisible to QuickStart

**Severity:** LOW
**Evidence:** QuickStart provider-readiness probe calls `load_provider_key` at `tui.py:737-741`. Journalled key reader only installed at `tui.py:810` (`_register_saved_key_reader`). `read_saved_secret` returns `None` immediately when no reader registered (`credentials.py:185-186`). Two `load_provider_key` calls in same startup return different answers.
**Reproduction:** Fresh non-recurring workspace with vault-stored key.
**Impact:** QuickStart shows "no key" when a key exists. Minor UX inconsistency.
**Root cause:** Reader registration ordered after QuickStart probe.
**Confidence:** HIGH — verified by call graph.

---

## F-12 · Dead/duplicated code in MemoryConfirmScreen

**Severity:** LOW
**Evidence:** `MemoryConfirmScreen.__init__/compose/on_mount/on_button_pressed` at `tui_screens_approval.py:600-626` are byte-for-byte copy of `WorkspacePackConfirmScreen` (`:558-587`), overridden by `:627-653`. Copy still carries `id="workspace-pack-title"` (`:606`). `action_cancel` defined twice (`:655` and `:658`).
**Reproduction:** Read source.
**Impact:** Maintenance burden. Confusing for readers.
**Root cause:** Copy-paste without cleanup.
**Confidence:** HIGH — verified by source comparison.
