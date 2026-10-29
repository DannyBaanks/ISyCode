---
name: isycode-icons-motion
description: "Choose and implement meaningful ISyCode TUI function/status icons and restrained operation-driven motion with Unicode, ASCII and reduced-motion behavior. Use for icon/state changes or Its Hover-inspired references, not terminal font installation."
---

# ISyCode icons and motion

Load [the shared visual standard](../isycode-design/references/visual-standard.md) if needed. Follow the accepted Ubuntu Sans Mono + Unicode profile; retain ASCII compatibility. Function identity and operation state are separate.

Use neutral symbols/text for availability or configuration, a check plus success text after a verified result, warning/cause for missing or unavailable dependencies, a cross/message for failed actions, and an explicit unknown/not-checked label when no check ran. Do not use a green dot for every item. A shield does not grant authority; an animated check does not prove success.

Use the preserved [icon map](../../../docs/design/2026-10-11-icons-typography/icon-map.json) as the starting vocabulary, not a promise of terminal glyph coverage. Reserve stable cell width and measure the actual terminal output. The comparator replaced missing `⧉`/`⑂` with `▣`/`↳` and uses local DejaVu fallback; actual terminal fallback still needs checking. Nerd Fonts is an optional route requiring a compatible font, not a hidden prerequisite for Unicode.

For motion, read the [preserved research](../../../docs/design/2026-10-11-icons-typography/INVESTIGACION.md) only when implementing a motion change. Its Hover components are SVG + React/Motion: do not import them directly into ordinary Textual character widgets. Use them as visual references and translate useful intent into a few fixed-width frames, or implement SVG references in the browser prototype. Keep architecture scope explicit.

Animate during a real running operation or briefly after its verified result. Stop on completion, cancellation, unmount and disabled motion; do not animate idle sidebar availability. Keep names, labels and layout stable, limit redraws to the affected widget, and provide a static/reduced-motion setting. Hover may enhance a reference demo, but understanding a state cannot require a pointer.

When copying/adapting assets, preserve pinned provenance and actual license notices. The preserved Its Hover LICENSE is Apache-2.0 despite MIT metadata; Tabler SVGs are MIT; Nerd Fonts combines several licenses, with the chosen Octicons/Seti glyph families listed as MIT. A later library update needs its own license check. Current copies and notices are already in `docs/design/2026-10-11-icons-typography/`; reuse them without duplicating a large icon catalog.

Verify state transitions, reduced motion, cancellation/unmount timer cleanup and Unicode/ASCII widths for the affected surface. Describe browser-only animation or font-table checks as such rather than calling native terminal animation verified.
