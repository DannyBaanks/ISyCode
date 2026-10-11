---
name: isycode-text-copy
description: "Implement or review ISyCode content-box expansion, mouse text selection and exact-range or explicit whole-box copying without gesture overlap. Use for text cards and clipboard interaction, not generic menu activation."
---

# ISyCode text selection and copy

Load [the shared standard](../isycode-design/references/visual-standard.md) if needed. This is the accepted behavior target; inspect current handlers rather than assuming it is already implemented.

| Input | Target behavior |
| --- | --- |
| Simple click on content | Focus; no expansion or clipboard write. |
| Space on focused non-editable content box | Expand/collapse; the only expansion gesture. |
| Space in editable input | Insert a space, without toggling an ancestor. |
| Double-click on content box | Open copy menu; no expansion or immediate copy. |
| Mouse drag | Select exact visible characters; no content-box activation. |
| Copy selection / Ctrl+C with a selection | Copy only the selected range. |
| Explicit whole-box option | Copy that box's retained plain content through the owner. |
| Escape in copy menu | Close without copying; restore useful focus/selection. |

Keep Enter activation on real buttons/options. Inspect both the container and its title/descendant bindings: changing `ExpandableBox.BINDINGS` alone may leave inherited title or click expansion active. Apply the target to affected `ExpandableBox`, `ThoughtBlock`, `CommandOutputCard` and text-preview paths without broad event interception.

Capture the original selection/source box before a menu changes focus. Map the selected display range back to retained plain text. Preserve the selected whitespace, tabs, Unicode and newline boundaries; omit unselected titles, borders, line numbers and ANSI markup. Wrapped visual rows must not add newlines that were absent in the source. Zero selection never falls back to copying everything. Do not trim, normalize or concatenate the whole box as a substitute for range extraction.

Reuse `SelectableText`, `_request_clipboard_copy` and `ClipboardOwner` where applicable. Whole-box copy may require an explicitly supported source contract: inspect it rather than disguising a full box as a mouse selection. Retain Workspace Authority, IsySentinel, execution-owner and journal checks. A toast or animation follows the owner's result; a menu opening is not copy success.

Verify partial-line and two-line copying, leading/trailing whitespace, tabs, Unicode, reversed drag, wrapping, scrolling, collapsed text, zero selection, denied copy, Escape and editable-field Space. A fixture proves only its payload/owner behavior; verify actual clipboard text in the terminal separately when available.
