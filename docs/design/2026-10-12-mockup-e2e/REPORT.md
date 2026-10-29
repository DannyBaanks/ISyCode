# Accepted Textual menu design: implementation and verification

Work started on 2026-10-12 and final verification continued on 2026-10-13
(America/Mexico_City). The implementation lives in the primary ISyCode checkout
on local `main`. The accepted reference is proposal 1, **Contraste esencial**.
This report concerns the Textual application, not ISyCode-IDE/Qt.

## Implemented behavior

The native menus now share black surfaces, thin muted frames, regular white body
text, cyan focus and selection, short headings, bounded scrolling and explicit
actions. The common palette also covers Textual select overlays. The landscape,
cat, prompt and actual permission/execution owners remain part of the product.

| Reference surface | Native implementation |
| --- | --- |
| Settings | Four categories; option/current value/help; provider and model entries; cross-category search; narrow stacked navigation. |
| Providers and models | Search/list/detail preview; explicit model choice; current model distinct from preview; provider/model identity survives catalog refresh. |
| Overview and Files | Flat sections; meaningful function/state marks; file tree and highlighted preview preserve source text. |
| Authority and welcome | Actual workspace mode and capability values; compact review/cancel actions and scopes. |
| Sessions | Searchable preview and explicit Open/Close; existing save, rename, fork and delete contracts. |
| Multi Harness | Compact inspection and repair proposals using real harness evidence; no parallel model execution invented from the reference illustration. |
| Edit and command review | Complete scrollable unified diff/argv; pinned buttons; default rejecting focus; unchanged approval payloads. |
| Copy and content | Space-only expansion; double-click copy menu; exact mouse range; separately explicit whole-box copy. |
| Connections, MCP and Gateway | Shared form/review anatomy; masked secrets; retained invalid drafts; bounded editors; complete target metadata. |
| Journal, commands, roles and context | Shared searchable option/value/help and preview patterns, using existing actions and scopes. |
| Ideas, queue, output and questions | Scrollable content; reachable controls; empty process list disables Stop; long questions keep answer/cancel accessible. |
| Folders, credentials, subagent and RTK | Same palette and compact actions; existing authority and result contracts retained. |

Unicode and ASCII fallbacks remain available. Skill availability is a neutral
catalog state; green is reserved for actual positive states. Terminal fonts
belong to the user's terminal profile, so this change does not mutate that profile.

## Source revisions

- `a425b32e9a2c245d8197dc63a7db6eb7b3363b04`: integration base. Remote main
  was merged into the already accepted source tree without deleting files.
- `ad70de9`: complete native menu implementation, capture tooling and launcher migration.
- `2a96e9e`: shared select/dropdown palette and interaction regression.
- `8bf4062`: separately scoped historical G8 manifest recovery and provenance.
- `7ecbe9f19f7b2f113945598d11b977b1d1f19e6d`: model identity/reasoning fixes.
- `8c668a307daf475bbc4ed14dc639b425a7f7d061`: final runtime source; readable
  compact model rows and an isolated DNS witness in the fake retry test.

Independent review found two P2 regressions in `2a96e9e`: positional model IDs
could apply the wrong model after catalog recomposition, and Settings omitted
the provider reasoning preset. Five focused regressions failed before correction
([raw output](evidence/review-regressions-red.txt)); the fixes retain the stable
`provider|model` payload and use the same reasoning default as Provider.

The resolved default now receives the current-model marker even before a model
is explicitly saved. Removed or filtered previews cannot enable Choose.
Independent re-review approved `7ecbe9f` and exercised reordered catalogs,
removed/hidden selections and identical model IDs under different providers.
The review was read-only. [Review record](evidence/independent-ui-review.json).

Visual inspection of native captures then exposed an additional issue: generic
focused-button borders consumed the sole model row, hiding its label. Three
compositor regressions reproduced it at all supported sizes. Model rows now use
only the cyan left indicator and regular body text, including subagent choices.
[Negative output](evidence/model-row-visibility-red.txt), [corrected focused run](evidence/final-row-retry-focused.txt).
Independent re-review approved `8c668a3`, including child-row compositor probes
at all three sizes and review of the narrowly scoped DNS fixture.
[Final review record](evidence/independent-final-row-review.json).

The full run on `7ecbe9f` had one retry-test timeout. Its transport was fake, but
the real provider owner still resolved DNS before calling it. Controlled DNS
denial reproduced the timeout and a public-address fixture passed. The test now
pins that DNS witness, keeping the owner and policy checks active. The same
denial injection no longer affects the fixture. No product network policy was
changed. [Negative](evidence/retry-dns-negative.txt), [control](evidence/retry-dns-control.txt), [isolated fixture](evidence/retry-dns-isolated-fixed.txt).

## Verification evidence

- Focused selectors/Settings after the fixes: **28 passed**. [Raw output](evidence/review-regressions-fixed.txt).
- The earlier complete hermetic run on `ad70de9`: **1,947 passed, 3 skipped,
  11 deselected**. [Output](evidence/full-final.txt), [command and source hashes](evidence/full-final-command.json), [no source drift](evidence/full-final-result.json).
- The failed `7ecbe9f` run is preserved:
  [output](evidence/full-reviewed.txt), [command/source hashes](evidence/full-reviewed-command.json), [result](evidence/full-reviewed-result.json).
- The complete final run on `8c668a3`: **1,956 passed, 3 skipped, 11 deselected**;
  pytest exit 0 and no source/script/test drift.
  [output](evidence/full-complete.txt), [command/source hashes](evidence/full-complete-command.json), [result](evidence/full-complete-result.json).
  The outer exec-session poll separately reported 143 after the completed child
  output/result was written; its cause is NOT_DEMONSTRATED and is recorded
  [without replacing the child result](evidence/full-complete-orchestration.json).
- Final affected-flow run: **57 passed**, covering selectors, text/copy,
  cancellation/retry and subagents. [Output](evidence/final-row-retry-focused.txt).
- Native Textual exports: 25 representative views at each of 80×24, 100×30 and
  140×40, plus preserved select-palette variants. A fresh 25-view 140×40 gallery
  was exported after the identity/reasoning fixes. Six fresh model/subagent-row
  views cover all three sizes on `8c668a3`, and the galleries point to these
  final variants. [Final gallery](screens-reviewed-140x40/index.html), [row metadata](evidence/final-row-captures.json).
- Real installed command in an 80×24 PTY: Settings opened through SGR mouse
  input, clean exit 0, no traceback on `8c668a3`. [Result](evidence/native-complete-result.json), [raw terminal stream](evidence/native-complete.ansi).
- Actual installed command resolves `tui.py` from this checkout's `src/`.
  [Import witness](evidence/installed-source.json), [launcher targets](evidence/launcher-after.json).
- Real copy roundtrip: native widget drag/Ctrl+C and double-click menu ->
  ClipboardOwner/Sentinel/grant -> xclip on a private Xvfb display. Forward and
  reverse two-line ranges, explicit menu selection and whole-box copying were
  byte-exact, with four verified receipts. Copy was denied before the grant;
  Enter did not expand the box and Space did. The user's desktop clipboard was
  untouched. [Result](evidence/clipboard-x11-result.json), [raw output](evidence/clipboard-x11-log.txt), [executed runner](evidence/clipboard-x11-runner.py).
- Isolated wheel build from `8c668a3` succeeded; includes presentation module,
  model selector, TCSS and English/Spanish/Chinese catalogs. No runtime package
  installation or checkout build tree replacement. [Build output](evidence/wheel-complete-build.txt), [asset/hash result](evidence/wheel-complete-result.json).

The original failures and earlier outputs remain preserved. SVGs are native
Textual exports, rendered with librsvg; the gallery HTML only displays them.
The final evidence index is [SHA256SUMS](SHA256SUMS), covering all preserved
artifacts in this directory except the index itself.

## Launcher activation

The user explicitly approved replacing only `~/.local/bin/isycode` after tests.
The former symlink was moved to a same-directory timestamp/PID backup; the old
runtime, user keys, conversations and preferences were preserved. The command
now targets this checkout's `scripts/isycode`, which prepends its own `src/`
while retaining the caller's project directory. Existing open sessions need a
restart to load the new code.

[Original manifest](LAUNCHER-MANIFEST.json), [activation output](evidence/launcher-activation.txt).

## Historical gates and limits

The G8 correction restores the exact originally reviewed manifest; it does not
approve this HEAD or authorize a release. Its raw output and both conflicting
historical candidates remain preserved. Independent review approved only that
restoration. [Provenance and recommendation](g8-provenance/RECOMMENDATION.json).

`validate_gates.py --require-approved` still rejects the current source, with
the retained historical-source mismatches and unapproved milestones.
[Current negative result](evidence/gate-complete-current-negative-second.txt).
No dependent milestone or affected capability was released, and no tag, GitHub
push or PR was created for this local integration.

**NOT_DEMONSTRATED:** live provider inference, live optional Gateway/MCP account
flows, physical desktop clipboard roundtrip and the user's terminal font
rendering. Integration-marked tests were excluded; the full run is hermetic.
The original G8 summary alone cannot prove the historical process's executed
source SHA. These limits do not turn fixture data into live service evidence.
