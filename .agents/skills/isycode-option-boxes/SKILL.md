---
name: isycode-option-boxes
description: "Add or revise ISyCode Textual option boxes, searchable selectors, list/detail dialogs, forms and copy menus using the accepted visual patterns. Use for component construction, not general chat text or unrelated products."
---

# ISyCode option boxes

Load [the shared visual standard](../isycode-design/references/visual-standard.md) if it is not already in context. Choose a pattern from [option-box contracts](references/option-boxes.md) rather than adding another visual family.

Inspect the current screen and its handlers. Reuse its data source and activation path; replacing list chrome does not authorize activating accounts, models, commands or grants. Separate preview/current/selected state from the action that commits a choice. Use one cyan focus/selection, plain black surfaces, readable help and explicit action labels.

For content boxes, follow [text/copy behavior](../isycode-text-copy/SKILL.md). List choices and real buttons still activate with Enter; the Space-only expansion rule is for content containers, not every control.

Use measured terminal cells, bounded modal height and a scrollable content area. Keep search, dismiss and primary actions reachable in 80×24. Search typing should not activate a result or steal Space from the input. Empty, loading, disabled and error states have explanatory text; do not substitute a success-looking icon.

Verify the changed opening, filtering, selection, activation, cancellation and focus-return paths. Show the affected view and report any remaining runtime gap. If only a mockup was requested, keep it a mockup rather than silently adding a production component.
