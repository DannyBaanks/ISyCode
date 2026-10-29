# ISyCode TUI navigation and account controls

**Status:** approved by Danny on 2026-09-27; implementation in progress.

## Product intent

Keep the chat as the main surface while making commands, integrations, models,
files, and role presets discoverable without scrolling through a flat list.
The visual language stays terminal-native: compact buttons, bordered popup
windows, keyboard selection, mouse selection, and the existing Crush-inspired
dark palette.

## Interaction model

- The bottom bar contains `Sidebar`, `Providers`, `Role`, and a right-aligned
  settings gear. The footer no longer repeats shortcuts or send instructions.
- Enter sends and Shift+Enter inserts a newline. Sending remains a keyboard
  action in the composer; no duplicate send button is shown.
- Typing `/` by itself opens a small popup with ten semantic branches:
  Skills, Models, MCP, LSP, Files, Roles, Providers, Session, Workspace, and
  Commands. A branch opens a scrollable second level. Escape/back returns to
  the prior level. Search filters the current level.
- The gear opens Settings. Its Commands/Shortcuts view shows every active
  keyboard binding, including bindings hidden from Textual's default Footer.
- Provider selection separates IsyMotron's executable completion presets from
  OpenISy's provider inventory (`GET /provider`) and auth metadata (`GET /provider/auth`). API keys use the external IsyMotron
  credential store and are never echoed. OAuth is shown only as an OpenISy
  capability until an inference-only bridge can consume it without granting
  OpenISy tools authority over IsyMotron actions.
- Role selection contains two visibly separate catalogs: OpenISy primary and
  subagents; and the eight ISyCo CLI motor roles. Selecting a conversational
  preset changes only chat guidance. Motor entries are descriptive shortcuts;
  the TUI does not execute those subprocesses or imply that they are chat
  agents.

## Security and truthful states

- Workspace Authority + ISySentinel are the security authority for local
  product actions. The earlier IsyMotron-only execution direction is superseded
  by `docs/design/isysentinel-security-boundaries.md`.
- A listed MCP, skill, OAuth method, role, or provider does not imply it can be
  invoked by this TUI.
- Credentials remain outside the project tree, are masked at input, saved with
  restrictive permissions through IsyMotron's existing store, and never
  displayed in transcript or settings.
- UI status distinguishes configured, missing credential, OpenISy-only,
  unavailable, and disconnected states.

## Acceptance

1. The prompt opens the two-level semantic palette when `/` is typed; lists
   scroll, search, accept mouse/keyboard, and close with Escape.
2. The bottom bar has no send button, shortcut clutter, or `ctrl+b` footer
   hint; the gear contains a complete shortcuts list.
3. Providers list all IsyMotron presets and real credential state; choosing a
   provider changes the active session provider. Key entry is masked and
   persists outside the repository without echoing the secret.
4. OAuth metadata, when OpenISy is configured, is labelled as belonging to
   OpenISy and is not falsely presented as an active IsyMotron credential.
5. Role selector separates OpenISy agents/subagents from ISyCo motors and
   identifies which options change chat guidance vs. only describe a CLI motor.
6. Narrow terminals retain access to the bar and popups; all actions remain
   usable without a mouse.

## Explicitly deferred

OAuth token exchange/refresh for IsyMotron, executing ISyCo motors from inside
the TUI, activating OpenISy skills/MCP tools from ISyCode, and multi-model
Roundtrip remain separate work requiring their own adapters and authority
contracts.
