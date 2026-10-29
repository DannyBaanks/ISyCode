---
name: isycode-settings-sidebar
description: "Design or revise ISyCode Textual Settings navigation and Overview/Files sidebar structure using grouped settings, flat sections and readable status rows. Use when editing these surfaces, not the separate ISyCode-IDE shell."
---

# ISyCode Settings and sidebar

Load [the shared visual standard](../isycode-design/references/visual-standard.md) when needed. Settings is the highest-priority visual surface in the accepted direction.

**Settings:** use Conversation, Preferences, Permissions and Connections as categories. Show setting, current value and local help in the content area, without repeating the category on every row. A focused category and active setting need distinguishable focus/selection. Keep search and Escape/back available. Preserve actual per-workspace/global preference scope and permission semantics; do not change a grant while merely previewing an option. At narrow widths replace the side category column with a compact category chooser or stacked navigation that leaves actions reachable.

**Sidebar:** keep Overview/Files as clear tabs. Use a flat section for Sentinel/Authority, MCP, languages, Skills and connections; expand only relevant detail instead of nested borders. Reserve space for the status column. Wrap a long name or put the full value in detail rather than clipping the meaningful cause. Configured, ready, missing executable and sandbox unavailable are different states. Skills availability is neutral, not a green pass.

**Files:** use stable tree indentation, a readable search and a useful preview height. The file preview should not collapse to one visible line under metadata. Keep file actions and Settings accessible with the rail open in 80×24. Restore the editor's focus when starting a new conversation or dismissing navigation.

Inspect `tui_app_rail.py`, `tui_app_menu.py`, shared widgets and the affected TCSS. Use [option-box patterns](../isycode-option-boxes/SKILL.md) for list/detail changes and [icons/motion](../isycode-icons-motion/SKILL.md) for status presentation. Verify the changed tab/category, scroll, back and focus paths, and check Spanish after repaint. Do not mark the historical audit issues fixed without reproducing their scenarios on the new code.
