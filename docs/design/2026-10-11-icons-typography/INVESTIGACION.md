# ISyCode: iconography, typography and motion direction

Date: 2026-10-11. Scope: design research and a local HTML comparator. No production TUI code or terminal preferences have been changed. This extends the earlier audit and menu design; it does not close their findings.

## Accepted direction

Danny selected proposal 1, **Contraste esencial**, then explicitly selected **Ubuntu Sans Mono, Unicode, 14 CSS px, line-height 1.3** in the comparator. Those values are now its initial profile. `accepted-profile.json` records the selection and its limits. The temporary attachment path is no longer present, so its file hash is `NOT_DEMONSTRATED`; no hash has been invented.

Keep black surfaces, white primary text, muted secondary text, a cyan focus state, thin consistent borders and a flat sidebar. Keep the landscape, cat and chat identity from the accepted composition. Settings is the main visual priority. Font size and line-height here describe browser styling; converting them to a real terminal's point size and cell metrics requires calibration.

## Libraries checked against primary sources

| Library | Verified source | Fit and limits |
| --- | --- | --- |
| [Its Hover](https://github.com/itshover/itshover) | Pinned `e5fc90512d9bcd8e6cba407ebf88cb9458989ca3`; actual [LICENSE](https://github.com/itshover/itshover/blob/e5fc90512d9bcd8e6cba407ebf88cb9458989ca3/LICENSE) is Apache-2.0 | SVG geometry and React/Motion components. Suitable for the browser reference. A plain Textual character widget cannot directly execute React or an SVG component. Native text-frame equivalents need implementation and terminal checks. |
| [Tabler Icons](https://github.com/tabler/tabler-icons) | Pinned sources and MIT license in `asset-sources.json` | A coherent static line-icon reference; retained as an alternative in the comparator. SVG is not a terminal glyph. |
| [Nerd Fonts](https://github.com/ryanoasis/nerd-fonts) | Pinned source, [aggregate license](https://github.com/ryanoasis/nerd-fonts/blob/master/LICENSE) and [glyph collection notices](https://github.com/ryanoasis/nerd-fonts/blob/master/src/glyphs/README.md) preserved locally | The catalog with more than 10,000 glyphs may be the one Danny remembered: an inference, not identification of an exact 11,000-icon repo. Its code is MIT, but the whole font/icon catalog is not uniformly MIT. This demo selects MIT Octicons and Seti/original glyphs. |

Its Hover's package metadata and one README feature still mention MIT, whereas its actual LICENSE and final README license section say Apache-2.0. The comparator preserves both original metadata and the Apache license, and labels the adaptations accordingly. It does not relabel the library MIT. Original TSX is preserved byte-for-byte; derived SVG and motion files carry modification notices and attribution. No NOTICE entry was found in the pinned recursive repository tree.

The three alternative text fonts are JetBrains Mono NL, Cascadia Code and Iosevka Term, downloaded as Nerd Font Mono variants. Their underlying text font licenses are OFL; bundled glyph collections have separate terms. Ubuntu Sans Mono remains the selected text face and uses Ubuntu Font Licence. The local DejaVu Sans Mono symbol fallback retains Bitstream Vera and DejaVu public-domain notices.

## Typography and symbols

Use regular weight for body text. Reserve emphasis for headings, selected items and actions. Disable programming ligatures in this exploration so `!=` and `=>` remain literal. Align names and values in stable columns and reserve a symbol column, rather than letting a changing symbol move the label. The comparison image uses the real font files with Pillow's BASIC layout engine; it is not an AI approximation of font appearance.

The downloaded Nerd Font Mono files contain all 21 mapped glyphs, and their advances equal the ASCII `M` advance. That verifies font data, not actual terminal rendering. Ubuntu Sans Mono itself lacks most of the proposed Unicode symbols. The comparator therefore keeps Ubuntu for text and uses an unmodified local DejaVu Sans Mono copy for missing symbols, scaled to its text advance using CSS `size-adjust`. Two earlier proposed symbols, `⧉` and `⑂`, were also missing from this fallback and were replaced by `▣` and `↳`. `profile-font-verification.json` records the checks. CSS fallback and scaling cannot be presumed to work identically in GNOME Terminal or other terminals.

The [Textual FAQ](https://textual.textualize.io/FAQ/) places terminal font selection in the terminal configuration. ISyCode should expose icon mode, contrast, density and motion preferences; a human guide should explain how to configure the terminal font. Do not add a font selector that falsely claims to change an arbitrary terminal's face, or silently require a patched font when Unicode was selected.

Separate **function** from **state**. A plug identifies connections; its text says whether they are configured or checked. A shield identifies authority; it is not proof of permission. Skills being available is neutral information, not a green success result. Always include a label or status text with the symbol.

| Meaning | Presentation |
| --- | --- |
| Available / configured | Neutral white text and the function icon |
| Verified successful result | Check mark, restrained green, outcome text |
| Warning / missing executable / unavailable sandbox | Warning symbol, amber, specific cause |
| Failed action | Cross, red, actionable error text |
| In progress | Finite or state-driven frame animation, task label |
| Paused / disabled | Dash or pause mark, muted text, explicit state |
| Not configured / not checked | Neutral label; never green merely because a row exists |

## Motion proposal

`preview.html` now includes six Its Hover examples: CopyIcon, TerminalIcon, RefreshIcon, PlugConnectedIcon, ShieldCheck and SimpleCheckedIcon. Their geometry comes from preserved original TSX. The standalone demo adapts their motion to the Web Animations API, adds keyboard focus/click activation and finite Unicode frame analogues, and respects both the reduced-motion checkbox and the operating system's reduced-motion preference. It does not run React/Motion itself. Copy, command and connection buttons in this section are visual examples and perform no product action.

For the native TUI, translate intent into a small number of stable text cells. Animate only while a real operation is running or briefly after its confirmed result. Stop timers on unmount, cancellation and disabled motion. Do not continuously animate idle sidebar entries or make hover necessary for understanding state. For copy, show success only after ClipboardOwner reports success; do not animate a success mark merely because a menu opened. For connections, distinguish configuration from a verified check. Optional graphics protocols would be a separate compatibility project, not a prerequisite for the selected Unicode profile.

## Apply the direction across every menu family

| Family | Shared treatment / improvement |
| --- | --- |
| Sidebar Overview | Flat sections, aligned status values, progressive detail, function icons; avoid nested frames and clipped names. |
| Sidebar Files | Same search chrome, tree indentation and preview surface; language identity without repeating green dots. |
| Settings | Conversation, Preferences, Permissions and Connections in a category column; setting/value/help in the content area; no repeated category prefix on every row. |
| Providers / accounts | Search, selected/current distinction, clear configured vs checked state and one explicit activation action. |
| Models | Same list/detail structure; separate browsing from choosing the active model. |
| Authority & Security | Shared rows and focus, explicit mode and grant state; retain per-action approvals and authority semantics. |
| Multi Harness | Same headings, separators, status vocabulary and repair proposal actions. |
| Sessions | Shared search/list/detail; new/open/rename actions and predictable focus restoration. |
| Ideas / queue / pasted text | Shared expandable content chrome and explicit review actions. |
| Command / process output | Task label, typed result state, retained output and receipt; motion tied to lifecycle. |
| Edit / batch / commit approval | Readable diff, explicit scope and consent buttons; consistent modal sizing. |
| Command / MCP / connection approval | Visible destination, command and scope; iconography never substitutes for approval. |
| File / text preview | Useful preview height, exact selectable text and explicit whole-box copy. |
| Palette / role / context / reasoning | One search/list/detail pattern and keyboard help. |
| Connection / MCP / Gateway / LSP / key forms | One field/error/help pattern; masked secrets and truthful verification state. |
| Welcome / mode / notices | Same decision template, bounded height and reachable buttons. |
| Journal / details / search | Shared result rows, clear evidence status and readable detail. |

All sample model names, grants, statuses and counts in the comparator are illustrative. They are not fresh service checks.

## Keep the requested copy contract

Simple click focuses a content box. **Space alone expands/collapses a focused content box**, while Space inside an editable field inserts a space. Double-click opens a copy menu without expanding or writing to the clipboard. Choosing whole-box copy is an explicit separate action. Dragging selects text; copying a selection copies only those exact characters, including two selected lines, whitespace and Unicode. No selection must never silently fall back to copying the whole box. Escape preserves usable focus and selection. Enter still activates actual buttons and menu choices.

The HTML selection example only displays the selected range or full text separately. It does not demonstrate real clipboard behavior, the new double-click menu, or Space expansion in ISyCode. Implementation must preserve ClipboardOwner, Workspace Authority, IsySentinel and the journal; visual redesign does not expand grants.

## Implementation order and acceptance

1. Resolve the earlier audit's stale mode header and unreachable Settings at 80×24; then new-chat focus, onboarding height, rail preview height and critical translations. The comparator does not fix these source bugs.
2. Introduce shared style tokens and icon/state helpers, then update Settings and both sidebar views. Reuse them across the families above rather than adding more local palettes.
3. Implement the content-box gesture contract and exact copy source mapping without stealing input-field spaces or consent-button activation.
4. Add opt-out motion with a static fallback and operation-driven lifecycle; default Unicode stays usable without Nerd Fonts.
5. Verify at 80×24, 100×30 and 140×40 in Spanish, high contrast, Unicode and ASCII. Exercise scroll/wrap, partial lines, two-line selection, reversed drag, cancelled copy, zero selection, focus restoration and actual clipboard output. Verify terminal symbol widths and font fallback on the user's terminal.

Observed source entry points: `tui.py:_idle_column`, `tui_widgets.py:Banner/ExpandableBox/ThoughtBlock/SelectableText/CommandOutputCard`, `tui_theme.py:_authority_capability_label/switch_row`, provider rows in `tui_app_menu.py`, catalog formatting in `tui_app_rail.py`, `isycode.tcss`, and `clipboard_owner.py`. Their hashes are recorded by the verification script as a baseline for later implementation.

## Verification limits

Font table checks, SVG parsing, source/asset hashes, JavaScript syntax, HTML resource references and local HTTP delivery can be verified on disk. The updated comparator's live browser interaction/rendering is `NOT_DEMONSTRATED`: browser control rejected binding the existing error-page tab because of URL protocol policy. No browser workaround was attempted. The original font comparator had been visually inspected earlier; that does not verify this revision's motion or responsive layout.

Production TUI icon animation, terminal font installation/calibration, corrected audit findings, real clipboard selection under terminal scrolling/wrapping, remote inference and connection checks remain `NOT_DEMONSTRATED` in this design phase. See `verification.json`, `verification.log`, manifests and `SHA256SUMS.txt` for this revision's actual evidence.
