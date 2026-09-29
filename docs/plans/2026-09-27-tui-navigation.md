# ISyCode TUI Navigation Implementation Plan

> **For agentic workers:** Implementation is being performed inline in this task; track completion in this document.

**Goal:** Deliver semantic slash navigation, compact bottom controls, provider configuration, and separated role catalogs in the running ISyCode TUI.

**Architecture:** Keep the Python/Textual app and IsyMotron runtime. Add small catalog/credential helpers, then present the data through one reusable two-level overlay and focused provider/role/settings overlays. OpenISy auth remains descriptive until an inference-only bridge exists.

**Tech Stack:** Python 3.12, Textual, Rich, IsyMotron provider module, OpenISy HTTP API.

**Spec:** `docs/design/2026-09-27-tui-navigation.md`

## Global Constraints

- Keep all secrets out of the repository, transcript, logs, and rendered UI.
- IsyMotron remains the authority for local actions; a provider, role, MCP, or skill listing grants no authority.
- Preserve Enter-send and Shift+Enter-newline behavior.
- Preserve unrelated dirty work and do not modify IsyMotron or OpenISy.

## Review Focus

- Slash typed in an existing draft must not erase the draft or steal text unexpectedly.
- Missing/unconfigured OpenISy server must leave all other palette branches usable.
- Provider selection without a configured key must clearly ask for one and must not call the provider.
- A selected agent role must not affect `/plan` authority or motor subprocesses.
- Small terminal sizes must not hide or clip every actionable control.

---

### Task 1: Catalog and credential helpers

**Files:** Create `isycode/catalog.py`; modify `isycode/config.py`, `isycode/openisy_client.py`.

- [x] Define semantic branch catalog, OpenISy agent/subagent catalog, and the eight ISyCo motor descriptions from audited source.
- [x] Add provider credential status/read/save helpers using IsyMotron's external store path with atomic writes and mode `0600` on POSIX.
- [x] Add read-only OpenISy provider/auth metadata discovery; unavailable endpoints return an explicit state.

### Task 2: Semantic slash palette

**Files:** Modify `isycode/tui.py`.

- [x] Add root and nested palette state, current-level search, back navigation, scrollable OptionList, and keyboard/mouse selection.
- [x] Open palette for an isolated `/` composer draft and from the Commands button.
- [x] Populate branches from live skills/MCP/LSP/model/provider/file/session/workspace/role/command inventories without inventing active capabilities.

### Task 3: Bottom bar, settings, provider and role selectors

**Files:** Modify `isycode/tui.py`.

- [x] Replace the Commands-only bar with Sidebar, Providers, Role and Settings; hide Textual Footer key hints and send affordances.
- [x] Add gear views for settings and all shortcuts.
- [x] Add scrollable provider picker, session selection, masked API-key form, and honest OpenISy OAuth availability state.
- [x] Add separate OpenISy conversational roles and ISyCo CLI motor role lists with clear behavior descriptions.

### Task 4: Documentation and interactive handoff

**Files:** Modify `ROADMAP.md`, `README.md`, `GUIA.md`.

- [x] Record delivered behavior, remaining OAuth bridge limitation, and manual launch steps.
- [x] Run static compilation and launch the TUI for visual/interaction inspection; resolve startup/render errors.
