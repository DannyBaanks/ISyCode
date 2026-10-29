# Accepted Textual design implementation

Started 2026-10-11; verified and documented 2026-10-12. Scope: the Python/Textual
ISyCode checkout. This is an implementation for review, not a release approval.

The accepted **Contraste esencial** direction now supplies the packaged palette
and shared TCSS. Settings has four categories, with search across categories;
Overview/Files uses flat sections. Content expansion uses Space, double-click
opens an explicit copy menu, and selected-range copying preserves whitespace,
logical newlines and source offsets through soft wrapping. Whole-box copying is
a separate choice. Selection alone never writes to the clipboard.

ClipboardOwner still requires the clipboard grant and Sentinel decision. The
new explicit `content_box` origin uses the same size, digest, journal and owner
checks. The model has no clipboard tool. No gate, authority preset, account or
integration was enabled by this change.

Function icons use Unicode with ASCII alternatives. Thinking uses two character
frames only while running; completion/unmount stops its timer. Reduced motion
keeps icons static and disables marquee timers. Its Hover remains a preserved
SVG/React reference, not an imported terminal animation library.

The skill palette is the authoring source. `scripts/sync_design_tokens.py` checks
the packaged JSON and TCSS variables; `--write` exports them. The wheel was built
and inspected for the new stylesheet, palette and copy module. Terminal font
preferences were not changed: Ubuntu Sans Mono / Unicode / 14 CSS px / 1.3 is
the accepted comparator profile, not a verified terminal point-size conversion.

See the [human guide](GUIA.md) and [native screen gallery](index.html). The latest
gallery uses `snapshots-20261012T075623Z/`: real Textual compositor exports with
isolated fixture data, rendered locally with librsvg. Models and command results
in those captures are illustrative fixtures. No provider inference ran. SVG
font rendering does not prove actual terminal glyph fallback. Older snapshots
and the failed ImageMagick conversion are retained as intermediate evidence;
the blank `settings.png` is not a valid UI preview.

## Verification and limits

The final UI regression group passed all **152 tests** on the final source.
Its exact command, clean-XDG scope, raw output and JUnit report are
`evidence/final-ui-*`. The separately corrected owner/fixture group passed
all 132 tests. These groups overlap and their counts must not be added.

Markdown is rendered as styled logical text to keep selection offsets exact;
tables use simple columns, and tab-containing fences preserve tabs rather than
expanding them for syntax highlighting.

- Focused UI/owner regressions passed, including exact partial/two-line copying,
  reverse drag, soft wrapping, tabs, zero selection, readonly selection restore,
  keyboard expansion, editable Space, grouped search, persisted reduced motion,
  timer cleanup, 80×24 onboarding choices and new-chat/mode-header focus.
- A real CLI launch in an isolated 80×24 PTY showed the Spanish onboarding and
  exited with Ctrl+Q, exit 0. No approval choices were submitted. Raw bytes and
  environment scope are in `evidence/cli-tui-*`.
- The full-suite attempts remain recorded, including failures. The later attempt
  passed 1,891 tests, with 6 failures, 1 skip and 11 deselections. Five failures
  came from a harness-level `ISYCODE_STATE_HOME` override that contradicted the
  tests' own fixture paths. The corrected clean-XDG run passed all 132 tests
  covering those files, memory and the changed interactions. This is not a claim
  that the complete suite passed.
- One historical G8 association remains unresolved: the recorded hash of
  `tests/test_visual_tui.py` matches the pre-implementation file, but not the file
  in the declared evaluated commit. Updating its gesture/theme assertions exposes
  that mismatch. `evidence/gate-drift.json` records all hashes. The historical gate,
  raw evidence and validator are unchanged. Release gates are not approved here.
- Physical-terminal mouse/clipboard roundtrip, real font fallback, live model
  services and new release acceptance remain **NOT_DEMONSTRATED**.

## Audit findings

| Finding | This implementation |
|---|---|
| F1: stale Classic/Security banner | Repaint on mode/identity changes; tested both directions without resize. |
| F2: Settings unreachable at 80×24 | Docked action and bar-width refresh when showing Files; tested by clicking it. |
| F3: new-chat focus | Return to composer after refresh; typed input tested. |
| F4: onboarding overflow | Bounded card, scrollable explanation and visible choices; tested with long paths. |
| F5: rail preview overflow | Metadata separated from selectable file body; owned read/receipt retained. |
| F6: untranslated/stale chrome | Copy controls, mode confirmation, write/command warnings and affected chrome translated; this is not a claim of complete translation coverage. |

`SHA256SUMS.txt` covers the saved artifacts; `evidence/source-hashes.json` pins the
source/tests used in the final focused checks. Earlier design/skill evidence
remains dated provenance, not a rewritten claim of production implementation.
