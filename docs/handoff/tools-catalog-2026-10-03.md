# Tools, catalog and Sessions — 2026-10-04

## Result

Real NVIDIA → ChatGPT subscription → NVIDIA completed with head_seq=4,
WAITING_FOR_HUMAN, and no current writer. GLM's TOKEN_A=roundtrip-682914
was read and repeated by ChatGPT. Nemotron read both that token and
REVIEW_B=subscription-verified and returned HUMAN_HANDOFF.
The old failed attempts remain in the hash-chained ledger. This run's ChatGPT
participant was selected as `auto`; its concrete resolved model is NOT_DEMONSTRATED.
The real account catalog separately returned eight concrete selectable models.

## Changes and operator guide

- `/models` automatically loads the selected account catalog; expanding another
  provider loads its catalog without selecting it. Groups and searches survive
  updates. Select a concrete model; only reasoning levels reported for that model
  are offered. Catalog failures remain visible and preserve the selection.
  Catalog choices also feed delegation and Iteration participant selection.
- The subscription connector explicitly permits `functions.exec` as the transport
  for declared dynamic ISyCode tools. It continues to prohibit built-in shell,
  filesystem, network and browser execution. No text-to-tool parser was added.
- `webfetch` is available in the TUI and children. First use of an HTTPS host asks
  for a scoped grant that displays the exact host. Headless requires an existing
  explicit host grant. Fetches pass through web.fetch / WebFetchOwner, existing
  Authority and RemoteReadBoundary, and emit receipts. No default grant is added.
  Public text/HTML/JSON only; no query strings, credentials, redirects, private IPs,
  compressed bodies or binary data. DNS is reviewed and TLS connects to that
  reviewed public IP. Limits: 512 KiB / 24,000 output characters. Web search is
  NOT_EXPOSED; webfetch is not a search engine.
- Bridge presence is run in a worker so the modal can receive Cancel/Escape.
- A single tool displays once. Consecutive same-operation calls have meaningful
  path/query labels and tree branches without a second arrow before the branch.
- Sessions show the friendly model before a potentially long title. First click
  previews; second opens. Keyboard selection keeps details current after resize.
- `Ctrl+D` with the Sessions list focused requests the same confirmed deletion
  of its highlighted ordinary session; it does not act in the composer.
- `[×]` is a red bold Unicode multiplication sign (font remains terminal-owned).
  It deletes only an ordinary saved conversation after confirmation using the
  existing one-shot request-bound authority, owner and receipt. Cancel preserves
  it; other conversations and recurring grants remain unchanged. Iteration
  artifact deletion is NOT_IMPLEMENTED: no compatible owner contract exists yet.
- Chat scroll keeps a persistent position thumb and upper/lower arrows, retaining
  existing wheel/drag actions. ExpandableBox/Thinking hints appear only with focus.
- Empty IdeaBox now explains `Ctrl+Shift+Enter`.

Queue interaction: Enter during a task queues FIFO. The same-width compact box
above IdeaBox selects a pending message on click; Space expands it. Empty Send
(or Enter on its focused title) attempts steering unless the model explicitly
reports no support. Unknown metadata permits a recoverable trial. No first chunk
within 30 seconds, empty response or explicit unsupported-steer error restores the
message to its original queue position and resumes the original request. Auth,
quota and network errors remain their own error categories. Esc restores selected
text without overwriting an existing draft; Ctrl+Enter is removed. [?] lists
confirmed support, including observations from prior launches.
ISyCode cancels/restarts only its existing owned provider request; native provider
turn/steer API support is NOT_DEMONSTRATED.

Ctrl+S toggles IdeaBox and ShellBox. Enter/Space or click on ShellBox opens the
session's sandbox processes and live output with the same persistent scroll thumb.
Stop cancels only the selected job; application shutdown awaits cancellation of
its jobs. `workspace_run` accepts `background: true` in this TUI: review/approval
happens first, then it returns a process ID without waiting for completion. Jobs
use the unchanged CommandRunOwner, staging, promotion, network denial and receipts.
Runs are serialized to avoid concurrent staging promotions; queued approval may
expire and fail closed. Default timeout is 120s, maximum 600s. These are bounded
session jobs, not persistent services or an interactive host shell.

Unknown image capability now permits sending the actual attachment. Explicit
image rejection is remembered; draft and image bytes survive failure. Generic
responses do not demonstrate vision. Durable capability observations contain only
provider, concrete model, feature, boolean and timestamp in
`$XDG_STATE_HOME/isycode/model-capabilities.jsonl` (default ~/.local/state).
No credentials, prompts or attachments enter this metadata file; observations do
not grant execution authority. `auto` is not persisted as a concrete model.

Model tester (Pillow optional dependency `vision-probe`):
```sh
PYTHONPATH=src python3 -m isycode.vision_probe --workspace /path/to/workspace --provider nvidia --output /tmp/new-unique-results.jsonl --timeout 30
```
It enumerates the real authorized account catalog, first probes text availability,
then challenges available models to read six random characters visible only in a
PNG. Exact matches demonstrate vision; OK, NO, OCR errors, timeouts and generic
400s do not establish unsupported vision. Only explicit modality rejection marks
it unsupported. 404 marks this chat endpoint unavailable, not proven provider
retirement. `/models` hides those rows but retains identifiers in an inspection
notice and the observation log. Rerunning the tester can restore availability.
`--availability-only` omits visual tests; repeat `--model` to target selected IDs.
Other providers can use the same command and schema. Results are never silently
copied to another provider's endpoint.

Restart ISyCode to load the changes. Select `/models`, choose a concrete account
model and its advertised effort; invoke webfetch on a public HTTPS page and review
its host prompt. In Sessions verify the prefix and `[×]` confirmation before deletion.

## Evidence

`docs/evidence/tools-catalog-2026-10-03/` contains the real canonical ledger,
readable turn projection, successful and failed execution receipts, safe live log,
real ChatGPT account catalog, and HTTPS Example Domain result (HTTP 200, journal PASS).
No credentials or opaque capabilities are stored in these evidence artifacts.
SHA256SUMS.txt covers the recorded evidence.

ITERATION_OWNER = DEMONSTRATED
ITERATION_APPEND_ONLY_STATE = DEMONSTRATED
AUTHORIZED_ITERATION_REFERENCE = DEMONSTRATED
TURN_CONTINUITY = DEMONSTRATED
SEQUENTIAL_MULTI_AGENT_LOOP = DEMONSTRATED
CROSS_PROVIDER_ITERATION = DEMONSTRATED
HUMAN_HANDOFF = DEMONSTRATED
SECURITY_COMPATIBILITY = DEMONSTRATED for tested gates; not universal security proof.

The broad visual audit remains a next pass: composer proportions in 80×24,
cat preservation in non-ready status, integration tiles/header counts, and the
unused ChatSessionsScreen. No files were deleted to remove that old screen.
No unrelated ROADMAP or Grok design edits belong to this change.

## Live model and process evidence (2026-10-04)

NVIDIA catalog: 81 IDs tested. Availability preflight: 17 available, 55 HTTP 404
at this chat endpoint, 9 NOT_DEMONSTRATED. The 55 are hidden in the normal Models
selector, never deleted from the original catalog or claimed provider-deprecated.
Of 17 available models, six passed the visual challenge, four failed it, and seven
were inconclusive. The earlier direct-image pass independently confirmed one
additional model (Nemotron 3 Nano Omni): seven unique confirmed model IDs across
both preserved runs. GLM 5.3 availability passed, vision NOT_DEMONSTRATED (stream
error); no unsupported-vision observation was written for it.

Real /usr/bin/bwrap execution in an isolated temporary project emitted
SHELLBOX_LIVE before exit; task cancellation killed and awaited it. This proves
actual process execution/cancellation in addition to ShellBox's UI fixture.
Focused owner/UI/probe/recovery tests: 42 passed. Full-suite result recorded below. The first direct-image run used 32 output tokens/20s; the second
used availability first and 256 tokens/30s. Older inconclusive results are retained,
not rewritten into negatives. Receipt IDs accompany provider successes.

## Final verification and attribution

Full suite: **1362 passed, 7 skipped** in 237.52s. Additional final recovery/model
state checks: **9 passed** (including two newly added negative cases and selector
restoration). Sessions/coverage: 30 passed. `git diff --check`: clean.
The previous full run's three failures and correction are preserved: coverage
snapshot was regenerated after that run had already collected its expectation;
component fixtures now disable the startup-captured periodic callback before
mounting, instead of patching an instance after the timer captured its method.
No product security checks were relaxed to make tests pass.

Main added code: capability_observations.py, vision_probe.py, web_fetch.py.
Modified runtime/UI code: tui.py, work_list.py, image_attachments.py,
reasoning_options.py, provider_errors.py, shortcuts.py, codex_connector.py,
command_runner.py (tool schema only), headless.py and the web.fetch action owner,
catalog/coverage/style registrations. pyproject.toml declares the optional probe
dependency. Tests and this evidence/report are attributable to this change.

Existing chat persistence formats, run_child, Authority/Sentinel decision rules,
CommandRunOwner process execution/staging/promotion, and provider transport are
reused. Unrelated ROADMAP and Grok audit/handoff files are not included.
Observations are advisory metadata, not execution grants. ShellBox jobs live for
the TUI application instance and are inspected/stopped through the UI; the new
background flag does not introduce a model-facing process-management tool.
The broader composer/landscape/rail design audit remains a separate visual pass.
