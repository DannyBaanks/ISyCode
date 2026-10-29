---
name: isycode-design
description: "Apply the accepted ISyCode Textual TUI design standard when adding or editing screens, menus, panels or visual behavior in ISyCode. Route to the relevant component skill; this does not cover the separate Qt ISyCode-IDE product."
---

# ISyCode Design Skills

Use the accepted **Contraste esencial** direction: black surfaces, white text, cyan focus, flat sidebar and grouped Settings. Danny selected Ubuntu Sans Mono, Unicode, 14 CSS px and line-height 1.3 in the comparator. These are design preferences; the terminal font and point-size conversion are not configured by Textual.

Read [the visual standard](references/visual-standard.md) for any TUI visual change. It separates accepted targets from behavior already demonstrated. Use [tokens.json](assets/tokens.json) as the shared palette and [tokens.tcss](assets/tokens.tcss) as a scoped starting stylesheet, adapted to the existing widget hierarchy. Do not load every component reference by default.

Choose the relevant skill:

| Work | Read |
| --- | --- |
| Option boxes, search/list/detail, selectors, copy menus or forms | [isycode-option-boxes](../isycode-option-boxes/SKILL.md) |
| Settings categories or Overview/Files sidebar | [isycode-settings-sidebar](../isycode-settings-sidebar/SKILL.md) |
| Expandable text, mouse selection, exact-range or whole-box copy | [isycode-text-copy](../isycode-text-copy/SKILL.md) |
| Function/status symbols or operation-driven motion | [isycode-icons-motion](../isycode-icons-motion/SKILL.md) |

Inspect the owning widgets and screen before editing; reuse the existing layout and owners. Keep style changes scoped to ISyCode rather than changing the user's terminal or unrelated products. Current user instructions may change this direction: implement the requested variation and record a material new choice in the shared standard instead of inventing a second silent palette.

Preserve the distinction between a design target and verified runtime behavior. Documentation or a mockup does not close an audit finding. Verify the changed flow at the relevant terminal sizes, including 80×24 when layout changes, and report what actually ran. Read [review criteria](references/review-criteria.md) only for the affected behavior.

The searchable [catalog](references/catalog.json) is the local registry. Use `python3 scripts/catalog.py list`, `search <words>`, `show <name>` or `check` from this skill folder; the commands are read-only. Registry descriptions and SKILL.md fingerprints should be updated when a skill changes.
