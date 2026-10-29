# ISyCode Workspace Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a private `.isycode/` configuration to each marked workspace while keeping all reads, writes, permissions, and command execution behind the existing ISyCode security owners.

**Architecture:** Add a bounded schema/loader for non-security workspace preferences, then connect reads and initialization to Workspace Authority, IsySentinel, WorkspaceWriteOwner, and GitOwner. Integrate effective preferences and command precedence into the existing TUI paths without moving grants, secrets, or runtime state into the workspace.

**Tech Stack:** Python 3.10+, existing ISyCode owners and TUI, JSON, pytest, temporary filesystem roots and local Git repositories.

**Spec:** `docs/superpowers/specs/2026-10-01-isycode-workspace-config-design.md`

## Global Constraints

- The nearest regular zero-byte `.isyroot` is the only persistent workspace identity; fallback launches never create `.isycode/`.
- `.isycode/` contains only version 1 `config.json` and `commands/*.md`.
- Preference precedence is product defaults → user-wide preferences → workspace preferences → session/request overrides.
- Workspace settings never define or change mode, grants, Sentinel policy, path/network/executable scope, approvals, credentials, sessions, receipts, or runtime state.
- Every workspace read and write uses its existing owner, Authority, Sentinel, approval, and journal path; no implicit grant is created.
- Canonical paths stay beneath the active `.isyroot`; symlinks and non-regular config files are rejected.
- `.gitignore` is changed only through the authorized workspace write path; never modify `.git/info/exclude`, index, commits, or history.
- Legacy `.isycode-commands/` stays readable; migration copies validated text and never deletes the source.

## Review Focus

- Nested `.isyroot` and fallback launch: only the nearest marked root loads config; fallback creates none.
- Malformed JSON, unknown schema, invalid values, oversized files, and symlink swaps: disable workspace config and retain user/product defaults.
- Authority, Sentinel, owner, or approval denial: no read result, file creation, ignore edit, or new grant.
- Tracked `.isycode/`, unreadable Git status, malformed/duplicate managed ignore blocks, unsafe `.gitignore`, and absent Git: explicit non-destructive result.
- Name collisions across user, new workspace, and legacy commands: user > `.isycode/commands/` > `.isycode-commands/`; migration preserves source bytes.

---

### Task 1: Versioned workspace preference schema

**Files:**
- Create: `isycode/workspace_config.py`
- Create: `test_workspace_config.py`
- Modify: `isycode/user_defaults.py` only if shared validators need a small public helper

**Interfaces:**
- Produces `parse_workspace_config(payload: bytes) -> WorkspaceConfigResult`; the result carries validated preference values and warning/error state. It performs no filesystem I/O and grants no filesystem authority.
- Accepts only `default_role`, `agent_steps`, `answer_tokens`, and `chat_token_budget` with the same choices and types as `UserDefaultsStore`; version is integer `1`; size is at most 64 KiB.

- [x] Test valid v1 values, omitted defaults, unknown-key warning/ignore, and invalid types/choices/version/JSON.
- [x] Test malformed JSON, unsupported version, unknown fields, exact allowed choice sets, and the 64 KiB payload bound.
- [x] Implement only pure bounded JSON parsing and field validation; filesystem metadata and reads are owned by Task 2.
- [x] Run `python3 -m pytest -q test_workspace_config.py`.

### Task 2: Owner-gated reads and initialization

**Files:**
- Create: `isycode/workspace_config_owner.py` (or keep the adapter in `workspace_config.py` if existing owner patterns make a separate module unnecessary)
- Modify: `isycode/git_owner.py`
- Modify: `isycode/workspace_write.py`
- Create: `test_workspace_config_owner.py`
- Modify: `test_git_owner.py`, `test_workspace_write.py`

**Interfaces:**
- Adds narrowly scoped `workspace.config.read`, `workspace.config.list`, and `workspace.config.write` actions handled by the existing workspace read/write owner paths. Their Systembilities permit only exact internal `.isycode/config.json`, `.isycode/commands/*.md`, `.isycode/commands/`, and `.gitignore` paths; generic chat file reads/writes continue to reject `.isycode/` as sensitive. Initialization uses a `WorkspaceWriteOwner` preview and fresh approval.
- Adds a read-only `GitOwner` path-inspection operation under `git.status` that returns whether `.isycode/` is tracked; denial or uncertainty is a stop result.
- Initialization returns an explicit outcome (created, already initialized, denied, tracked, unsafe ignore, or Git unavailable) and performs no index or commit operation.

- [x] Add internal config action IDs to the action catalog and exact owner bindings; generic workspace file actions still deny `.isycode/`.
- [x] Test denied reads/writes, missing approval, and Git path-check refusal; these leave files and grants unchanged.
- [x] Test tracked `.isycode/` refusal and safe untracked-repository ignore preview.
- [x] Test exact ignore rules, managed-block idempotence, newline preservation, malformed blocks, and non-repository behavior.
- [x] Implement canonical-path and no-symlink checks, owner-mediated reads/writes, and safe Git ignore checks.
- [x] Run focused config owner, GitOwner, and workspace-write tests.

### Task 3: Preference precedence and settings setup

**Files:**
- Modify: `isycode/tui.py`
- Modify: `isycode/agent_loop.py`
- Modify: `isycode/headless.py` only where it shares effective preference resolution
- Create: `test_workspace_config_tui.py`
- Modify: `test_user_defaults_mode.py`, `test_agent_loop.py`

**Interfaces:**
- Effective non-security preferences resolve product defaults → `UserDefaultsStore` → authorized valid workspace values → existing per-session/request overrides.
- Workspace setup/settings offers explicit initialization for `.isyroot` identities; confirmation runs the Task 2 adapter. Fallback workspaces do not show persistent initialization.

- [x] Test preference parsing and authorized TUI use; config is restricted to non-security fields by schema and owner.
- [x] Integrate effective settings into the TUI and agent/chat limits while preserving personal defaults.
- [x] Run focused TUI startup, workspace-config, and workspace-authority owner tests.
- [x] Test that persistent settings are hidden for fallback roots and shown for `.isyroot` workspaces; test initialization approval and cancellation through the TUI handler.
- [ ] The full settings-menu keyboard/pointer approval interaction suite remains unrun.

### Task 4: Workspace commands and compatibility

**Files:**
- Modify: `isycode/prompt_expansion.py`
- Modify: `isycode/tui.py`
- Create: `test_workspace_config_commands.py`
- Modify: `test_prompt_expansion.py`

**Interfaces:**
- Workspace command discovery merges validated new commands and legacy commands with precedence user > new > legacy; command reads are performed by the authorized workspace read owner.
- A user-invoked migration copies validated legacy command text into `.isycode/commands/` via the authorized write path, never overwriting a destination or deleting the source.

- [x] Integrate new command reads through the config owner and keep user > new workspace > legacy invocation precedence.
- [x] Test migration copies validated text, refuses collisions, and preserves source files.
- [x] Integrate copy-only migration behind a reviewed write diff.
- [x] Run focused prompt-expansion, config-owner, workspace-read, and workspace-write tests.

### Task 5: User guide and security regression

**Files:**
- Modify: `README.md`
- Modify: `GUIA.md`
- Modify focused workspace config tests only for discovered gaps

- [x] Document workspace placement, preference keys, precedence, initialization, ignore behavior, command migration, and `.gitignore` limits.
- [ ] Full non-integration suite run before the final updater-abort regression test and TUI coverage: 932 passed, 52 failed, 1 skipped, 11 deselected. Four representative failures reproduced on a clean archive of pre-change `HEAD`; latest focused batches pass (147 owner/schema/updater, 19 TUI startup/security/workspace-config, and 6 launcher tests).
- [x] Run `git diff --check` and inspect that no Authority/Sentinel policy or private credential path was added under `.isycode/`.
