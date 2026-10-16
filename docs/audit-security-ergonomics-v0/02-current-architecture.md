# 02 — Current Architecture

**Commit:** `b76377d` · **Date:** 2026-10-15

## TUI Layer Size

| Component | Lines | Files |
|---|---|---|
| `tui.py` (TUIApp core) | 3,541 | 1 |
| Mixin files (`tui_app_*.py`) | 8,444 | 9 |
| Screen files (`tui_screens_*.py`, `folder_screens.py`, etc.) | ~4,200 | 8 |
| Widgets (`tui_widgets.py`) | 903 | 1 |
| **TUI total** | **~17,089** | **19** |
| Security layer (`action_runtime.py`, `action_audit.py`, `workspace_authority.py`, `security.py`, `approvals.py`, `workspace_trust.py`) | ~5,200 | 6 |
| **src/isycode total** | **50,693** | **~120** |

## TUIApp Class Hierarchy (MRO)

```
TUIApp                          tui.py:324
├── SessionMixin                tui_app_sessions.py:181   (1,497 lines, 64 methods)
├── RailMixin                   tui_app_rail.py:46        (642 lines, 28 methods)
├── ProviderMixin               tui_app_providers.py:65   (1,065 lines, 64 methods)
├── AuthorityMixin              tui_app_authority.py:45   (847 lines, 26 methods)
├── RemoteMixin                 tui_app_remote.py:55      (866 lines, 27 methods)
├── WorkspaceMixin              tui_app_workspace.py:31   (704 lines, 37 methods)
├── ToolMixin                   tui_app_tools.py:60       (781 lines, 22 methods)
├── ChatMixin                   tui_app_chat.py:91        (1,093 lines, 12 methods)
├── MenuMixin                   tui_app_menu.py:507       (949 lines, 60 methods)
└── textual.app.App             site-packages
```

TUIApp itself defines 118 methods across: lifecycle (13), chat/composer (25),
menus (21), screens (4), approvals (6), defaults (5), providers (2), plan
pipeline (6), clipboard (4), rail/console/activity (32).

## Cross-Mixin Coupling (7 bidirectional pairs)

| Pair | Direction A→B | Direction B→A |
|---|---|---|
| Chat ↔ Session | 27 sites | 1 site |
| Session ↔ Tool | 6 sites | 8 sites |
| Provider ↔ Session | 4 sites | 3 sites |
| Rail ↔ Workspace | 6 sites | 1 site |
| Rail ↔ Remote | 1 site | 1 site |
| Authority ↔ Workspace | 1 site | 3 sites |
| Tool → Authority | 1 site | (one-way) |

Plus a directed cycle through 6 of 9 mixins:
Menu → Session → Tool → Workspace → Rail → Provider → Menu

## External attribute access per mixin

| Mixin | Distinct `self.*` | External | →tui.py | →other mixin | →framework |
|---|---|---|---|---|---|
| Session | 119 | 43 | 30 | 6 | 7 |
| Rail | 58 | 29 | 18 | 6 | 5 |
| Provider | 77 | 32 | 25 | 3 | 4 |
| Authority | 23 | 16 | 14 | 2 | 0 |
| Remote | 33 | 19 | 16 | 1 | 2 |
| Workspace | 49 | 30 | 27 | 1 | 2 |
| Tool | 61 | 36 | 20 | 15 | 1 |
| Chat | 69 | 47 | 27 | 17 | 3 |
| Menu | 70 | 68 | 21 | 44 | 3 |

## Authority / Execution Flow

```
User action
  → TUI handler (mixin method)
    → ActionRequest construction (action_id, workspace_root, target, params, execution_owner)
      → ProductActionGate.authorize(request, approvals, approval)
        → effect_policy.stamp(request)          # classification, fail-closed
        → authority.evaluate(request)            # Workspace Authority: grants + approvals
        → sentinel.evaluate(request, authority)  # IsySentinel: 20+ Systembilities
        → audit.record_decision(...)             # hash-chained journal append
      → ALLOW?
        → owner.execute(request)                 # Execution Owner runs the effect
        → gate.persist_receipt(request, receipt) # journal append (SUCCESS only)
        → ActionOutcome returned to TUI
      → DENY?
        → ActionOutcome(reason) returned to TUI
        → TUI renders yellow transcript line
```

Key files:
- `action_runtime.py:1780-1920` — ProductActionGate (authorize + persist_receipt)
- `workspace_authority.py` — WorkspaceAuthority (grants, approvals, mode)
- `security.py` — ActionRequest, SentinelDecision, SystembilityResult
- `action_audit.py:73-132` — ActionAuditJournal (hash chain, segments)
- `approvals.py` — ActionApprovalStore (one-use, digest-bound, TTL)

## Startup Sequence

```
Textual dispatch
  → Compose (widgets mount, rail placeholders painted)
  → TUIApp.on_mount (tui.py:646-699)
    ├── _refresh_usage()                    # sync
    ├── _apply_locale_chrome()              # sync
    ├── set_interval(1.0, _paint_work_status)
    ├── add_decision_listener(_on_journal_decision)
    ├── set_interval(5.0, _paint_sentinel)
    ├── run_worker(_load_sentinel_journal)  # fire-and-forget, group="sentinel-journal"
    ├── _mount_idle_board()
    ├── run_worker(_startup_workspace)      # fire-and-forget, exclusive, group="workspace-startup"
    └── [UI is now interactive]
         │
         └── _startup_workspace (tui.py:719-829)
              ├── [possible modals: QuickStart, WorkspaceSetup, WorkspaceMode, quiet trust]
              ├── ChatSessionOwner(...)     # may fail → _chat_session_owner = None
              ├── authority.set_mode(...)
              ├── await _offer_quiet_trust(...)
              ├── _register_saved_key_reader()
              ├── await _initialize_workspace()   # authority load + _load_directory
              ├── _refresh_lsp_status()
              ├── run_worker(_refresh_openisy)    # fire-and-forget
              ├── run_worker(_check_gateway_async) # fire-and-forget
              └── run_worker(_check_model)         # fire-and-forget
```

No readiness signal is emitted. No code awaits the startup worker.
The only test that waits for it polls `app.workers` (test_continuity_recovery.py:186-193).

## Menu Dispatch

- `MENU_DISPATCH` dict: 118 string→method-name entries (`tui_app_menu.py:386-505`)
- Consumed by `MenuMixin._select_menu_entry` via `getattr(self, handler_name)(entry)`
- Unknown kind → `_blocked_notice` (silent)
- `_render_menu(mode, title, entries)`: 44 call sites, 24 distinct static mode strings
- Only 4 mode values change layout behavior; the rest are labels
- No typed registry, no schema validation, no exhaustiveness checking

## State Architecture

| Source | Scope | Path/Key | Resolver |
|---|---|---|---|
| `ISYCODE_STATE_HOME` | global | env var override | `state_root()` |
| `XDG_STATE_HOME` | global | env var fallback | `state_root()` |
| `XDG_CONFIG_HOME` | global | env var | direct read |
| `~/.local/state/isycode/` | user | default state root | `state_root()` |
| `.isycode/` inside workspace | workspace | action-journal, trust | relative to workspace root |
| `UserDefaultsStore` | user | JSON file under state root | own path logic |
| `WorkspaceAuthority` | workspace | grants JSON under state root | hash of workspace root |
| `WorkspaceTrust` | workspace | trust record under state root | hash of workspace root |
| `ActionApprovalStore` | session | **no persistence** (in-memory) | constructor |
| `ActionAuditJournal` | workspace | `actions-{sha256(root)[:32]}.jsonl` | hash of workspace root |
| `~/.grok/auth.json` | user | grok CLI token (never read by ISyCode) | external |
| OS keyring | user | provider API keys | `credentials.py` |

42 distinct env vars read across 105 sites. 29 `state_root()` call sites across 24 files.
No single authority resolves all state paths.
