# ISyCode IDE — native correction review, 11 October 2026

## Findings

The reported duplicate navigation, empty initial editor and blank unlinked
GitHub details have been corrected. File types now use genuine vendored SVGs;
the terminal uses literal ASCII identifiers. The screenshot below is a native
widget render with private fixture data, not an account demonstration or a new
mockup. This review passes the requested corrections; it does **not** claim
pixel-for-pixel reproduction of the generated design references.

## Visual truth and evidence

- Sources: `docs/design/mockups/conversation.png`, `code-chat.png`,
  `github-sync.png`; hashes/provenance in their existing `manifest.json`.
- Exact user screenshots: `docs/verification/audit-baseline-20261011/`, copied
  unchanged from the two supplied PNGs; original paths and SHA-256 in manifest.
- Final implementation: `docs/verification/qt-polish-20261011-complete/`.
  See `conversation-1672.png`, `code-1672.png`, `github-linked-1672.png` and
  GitHub PR/issues/commits/Actions states. Every render has a SHA-256 receipt.
- Source and primary implementation pixels: **1672 × 941**. Logical Qt viewport
  **1672 × 941**, DPR **1**; no density scaling. Additional native captures:
  **1024 × 768**, **1366 × 768**, **1920 × 1080**. This is a native application,
  so CSS viewport and browser-console checks do not apply.
- State: dark theme, CODER, file open, same conversation across modes, file
  and exact-command approvals pending. Private local-example Ollama metadata
  is configured without connecting a provider. GitHub account `Fixture` and
  a linked folder five commits behind are synthetic. Neither fixture executes
  commands, applies changes, contacts accounts nor updates a real repository.
- Dynamic content differs from the reference: a short greeting file, one
  proposal, one conversation, local provider and fixture repository replace
  its Flask example, two files and ChatGPT subscription. Native OS titlebars
  are outside `window.grab()`; the mock draws its own window controls. These
  differences prevent a numeric pixel-fidelity claim.
- Full-view source/implementation pairs were presented together in the same
  visual inspection input for Conversation, Code + chat and GitHub. The last
  Code inspection includes the 1366 render showing the corrected scroll control.
- Focused pairs: `docs/verification/qt-polish-20261011-details-final/` contains
  `source-controls.png` / `actual-controls.png` and `source-files.png` /
  `actual-files.png`, with exact crop coordinates and hashes. Diagnostic crops
  preserve originals. They were inspected together for icons, typography and
  decision controls. Earlier unchanged card details also live in `...-details/`.
- Actual initial empty Conversation and a Textual `[PY] src/app.py` modal are
  preserved in `docs/verification/qt-polish-20261011-details/`. The empty
  inspector is hidden; provider setup remains actionable.

## Comparison history

| Severity and observed problem | Concrete correction | Post-fix evidence |
|---|---|---|
| P1: Conversation and Files selected the same layout | Route both buttons through `set_view`, swap editor/chat, retain session/draft | `...-complete/conversation-1672.png`, `code-1672.png`; navigation tests |
| P1: unopened editor used half the initial chat | Hide inspector until a file opens | `...-details/actual-empty-conversation.png`; opened-file retention test |
| P1: unlinked GitHub detail was an empty incoming-commits box | Read-only metadata and activity independent of local link; local actions conditional | `...-complete/github-1672.png`; no-link/partial-permission tests |
| P2: native toggle radius exceeded half its actual height | Minimum height and smaller radius | `...-b/` onward; final view/mode toggles |
| P2: heavy yellow approval surface and technical hash clutter | Charcoal/cyan card, collapsed identity/base, primary decision and full diff dialog | `...-b/`, focused final controls |
| P1: compact proposal minimum width clipped decision controls | Ignore horizontal size hint, adaptive headers/buttons, full diff dialog | `...-c/`, `...-complete/code-1024.png`; bounds test |
| P2: local Pull appeared below activity and oversized commits | Move local card first, collapse incoming commits, group actions | `...-e/` and final `github-linked-1672.png` |
| P2: file symbols were generic/absent, collapse glyph was empty | Official colored SVGs in tree/search/editor/proposals; sized Tabler menu button | Final focused files, asset receipts and icon tests |
| P2: scroll-to-end overlay covered commands at 1366 | Move button into layout outside transcript | `...-delivery/code-1366.png` before, `...-complete/code-1366.png` after; geometry/click test |

Here `...` refers to `docs/verification/qt-polish-20261011`. All iterations
are preserved with manifests; no earlier capture or raw test log was replaced.

## Required fidelity surfaces

1. **Fonts / typography.** Lato is installed (`fc-match Lato` →
   `Lato-Regular.ttf: "Lato" "Regular"`). Native labels use 14 px, body Markdown
   15 px, section hierarchy 17–27 px; code remains monospace. The raster mock's
   exact font identity is NOT_DEMONSTRATED. It is a visual direction, not a font
   specification. Short compact decisions and wrapping preserve readability.
2. **Spacing / layout rhythm.** Chat/editor reverse positions without replacing
   widgets. Files gives the editor a larger region and chat a maximum 500 px;
   Conversation retains project history. The initial editor is omitted. Native
   splitters, resizable content and vertical transcript scrolling are expected;
   persistent compose/mode controls remain reachable. Decision buttons stack
   at narrow widths. The explorer elides long names and exposes full tooltips.
3. **Colors / tokens.** Window `#0c121a`, content `#101924`, cyan `#08c7fa`,
   text `#e8f1fa`, secondary `#adbed1`; yellow denotes behind/pending, green
   verified/success, red rejection/failure. Heavy yellow card fills were removed.
   Flat native surfaces retain charcoal/cyan hierarchy; the mock's decorative
   gradients/glow are not treated as proof of an implemented effect.
4. **Image quality / assets.** Supplied neon cat PNG is retained without
   modification. Navigation uses official Tabler SVGs with MIT license and
   pinned source hashes. File types use unchanged vscode-icons artwork and
   its upstream attribution/license distinctions, not emoji or hand-drawn
   approximations. Python/JS/TS/JSON/YAML/folder icons are visible at native
   size; unknown files have an explicit generic icon. ASCII is literal text,
   not mislabeled Nerd Font glyphs. No font installation is required.
5. **Copy / content.** Navigation now describes distinct workspaces. Approval
   decisions remain review / once / exact-command always / reject. Technical
   base identity is available on demand. GitHub samples are bounded and labeled,
   section failures are unknown, Actions is all branches and commits are the
   default branch. Local synchronization remains independent. No fixture value
   or source mock account is asserted as the user's current account state.

## Expected differences and remaining polish

- The user-requested open-source file theme changes generic folder/Markdown
  colors from the mock. The supplied official cat replaces its stylized cat.
- Files concentrates on files rather than repeating conversation history;
  switching back reveals the same history and draft.
- GitHub now includes metadata/activity not present in the earlier sync mock.
  It uses a native local status card and expandable incoming commits instead
  of a decorative commit timeline. Changes cannot be applied from metadata.
- Compact full diffs open in a separate read-only review dialog, so the code
  view does not duplicate a large diff inside the narrow chat column.
- P3: decorative glow, richer file tabs/breadcrumbs and an exact typography
  specification could bring future styling closer to the reference. This
  delivery is an improvement with explicit native differences, not a promise
  that the complete IDE is visually identical to every mockup.

## Verification and implementation checklist

- [x] Distinct layouts retain draft, session and unsaved editor content.
- [x] Real SVG file types and ASCII proposals/workspace/tool states.
- [x] Remote metadata/activity without local link; bounded/partial states.
- [x] Account refresh invalidates verified styling; safe fixed-host links.
- [x] Existing Git fast-forward/review and command approval protections retained.
- [x] Four native viewports, source/implementation and focused comparisons.
- [x] Full suite: **228 passed**, raw `polish-accepted-regression-20261011.log`,
  exit status and SHA-256 in its JSON receipt. Private fixtures only.
  The final TUI parser also handles the leading newline actually emitted by
  the agent before tool results, so `[OK]`/`[ERR]` reach the ASCII renderer.
- [x] Spanish manual updated with actual menu usage and asset provenance.

Final result: **passed**
