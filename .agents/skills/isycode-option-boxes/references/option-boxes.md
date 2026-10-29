# Reusable option-box contracts

## Search / list / detail

Use for providers, models, sessions, roles, context, reasoning, command palettes and evidence search.

Structure: title + optional scope, one search field, a list with stable row height and selected/current distinction, detail/help for the focused row, then action/keyboard help. At wider sizes detail may sit beside the list. At narrow sizes stack it or open it as a separate view; preserve the list and actions. Do not place a large fixed-height detail panel above the primary action.

Typing filters. Arrow navigation moves selection. A single click previews/focuses a result. Enter or an explicit action applies it; label the action (choose model, open session, etc.). Keep any requested change to existing activation semantics scoped and verified. Content-copy double-click gestures must not accidentally apply a model or grant.

## Form / value / help

Use for connections, account fields, keys, MCP/Gateway/LSP setup and preference values. Align label/value rows, put help beneath the affected field, mask secrets and distinguish validation from configuration. Save/connect/check are explicit actions through existing owners. An invalid field keeps a useful error and input value; no silent clearing.

## Decision / diff

Use for welcome/mode decisions and edit/batch/commit/command approvals. State the concrete destination, scope and consequence; put the change or diff in the scrollable area, and keep consent/cancel reachable. Reuse approval contracts. A design pattern must not combine review and execution into a new implicit action.

## Copy menu

The menu opens on double-click of a content box without expanding it or copying immediately. Show **Copiar selección** only as usable when an exact range exists and **Copiar caja completa** as a separate explicit action. Preserve the source box and its selection while the menu receives focus. Escape returns focus without copying. Follow the text-copy skill for ownership and payload mapping.

Prefer existing widgets in `src/isycode/tui_widgets.py` and existing screen handlers in `tui_app_menu.py` / related screen modules. The [common TCSS asset](../../isycode-design/assets/tokens.tcss) supplies scoped style classes; it does not implement a selector or consent workflow by itself.
