# Summary: Multi Harness design

Revised the architecture document in place for 18 review issues and for two new semantic nodes. No ISyCode source was modified and nothing was committed.

- Design: `/tmp/grok-danny/grok-design-doc-2bbe6015.md`
- Review: `/tmp/grok-danny/grok-design-review-2bbe6015.md`
- Date: 2026-10-02
- Status: Draft

## What it specifies

Multi Harness is a semantic options graph for thirteen CLIs: `crush`, `qwen`, `opencode`, `claude`, `codex`, `grok`, `hermes`, `fx`, `openclaw`, `pi`, `kimi`, `cursor`, and `copilot`. Gemini is not a harness. `agent` is not a harness. A node is a meaning, not a shared JSON key.

Discovery probes `[executable, "--version"]` with no shell and a 3 second timeout. The thirteen probes run concurrently. Each line shows `Checking {Harness}…` until that probe returns. A successful probe unlocks one real directory. No response means no automatic read. Crush and Qwen readers accept that unlocked root when a later probe succeeds. They do not stay pick-only after the binary answers.

The screen is a new modal from the command-bar button **Multi Harness**. The Sessions control opens the in-place work list. `ChatSessionsScreen` is unused. The idea box stays a non-goal.

`roots.json` is `{"version": 1, "roots": {harness id: absolute path}}`. Overrides may only tighten an edge to `non_equivalent`, or ignore a semantic id so it drops out of `N`. Unknown ids are rejected. Picked paths reject `~/.config`, `~/.local`, and `~/.local/share` themselves. A named application directory under them can pass after confirm.

## Gap counts from automatic roots

The threshold is `N >= 4`. It is not 5 and it is not 13. ISyCode is not part of `N`. A failed probe does not count. Copilot stays locked.

- `user_skills` is N=4 and the only `ADD` row. The label is `Missing in ISyCode`. The click does not create a skill directory.
- `default_model` is N=5 and `ALIGNED`. Every live edge fails `copy_requires`, so there is no copy button. A later button sets `ISYCODE_PROVIDER` and `ISYCODE_MODEL`, then calls `save_provider_selection`. It does not construct `Provider`, does not load a key, and does not write `state.model`.
- `reasoning_effort` is N=3 and `WATCH`. Codex, Hermes, and FX settings count. Grok's session summary and FX's session `effort` do not.
- `ui_theme` is N=3 and `WATCH`. Cursor `display.mode` (`zen`) is a layout mode.
- `provider_endpoint` is N=4 and `DO_NOT_MERGE`.
- `prior_transcript` is N=7 and `ALIGNED`. The screen counts `len` from `ChatSessionOwner.list_conversations`. It does not call `ChatSessionStore.list_sessions` in `tui.py`.
- `enabled_plugins` stays N=3. OpenCode `plugin[]` is `non_equivalent` and does not raise it.
- `web_fetch` and `web_search` are separate nodes. Both targets are `absent`. Both are N=0 and `WATCH`. They are not `ADD`, and the click does not add a tool.

Hermes `web` has only `web.backend`, which is not a fetch or search switch. Kimi's Moonshot service rows stay endpoints and secrets. They do not increment `web_fetch` or `web_search`. Cursor `autoAcceptWebSearch` stays a non-transferable approval switch. ISyCode's chat tools are `workspace_list`, `workspace_read`, `workspace_grep`, and `workspace_search`. The Codex connector's `web_search = "disabled"` is not an ISyCode tool.

## PR split

Twenty mergeable PRs. One reader per harness. Probes run together and do not live in `tui.py`. The Cursor reader uses the live allowlist. The Copilot reader stays fixture-only, strips JSONC comments, then `json.loads`, and does not open the live folder until `copilot` answers. Transcript import is still the last PR: painted in the open chat, persisted with `record` only when sessions are enabled, `state=None`, and stopped on `DENY`.

This document is not a milestone and does not mark gates G0–G6.
