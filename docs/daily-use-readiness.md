# Daily-use readiness — updated 2026-10-02

## Audit follow-up (2026-10-02)

Classic and Security retain the same owner/Sentinel/journal boundary. Explicit
revocations win over Classic presets and configuration-action aliases. File
previews are bound to their approved content and displayed diff. Provider keys
remain isolated; malformed authority policies produce denied diagnostics rather
than crashing doctor. Incomplete/truncated streams do not authorize tool calls,
and transport errors never echo raw provider bodies into the chat. Each SSE
frame has a 1 MiB protocol limit, distinct from conversation/generation limits.

Offline tests cover these regressions; they do not establish live provider
authentication, multi-hour memory behavior or remote integrations.

## Continuity, compatibility and reported consumption

El paquete fija Textual 8.2.8, la versión usada por CI en Linux con Python
3.10 y 3.12. Permite seleccionar con el ratón las respuestas del chat; copiar
la selección sigue pasando por el permiso del workspace y su ClipboardOwner.
Chat shows model steps and tools in order and follows the bottom while preserving
manual history/search navigation.

New sessions retain complete tool notes without application-level count or
character truncation. All notes are supplied as explicitly untrusted,
potentially stale context on the next turn. Resume displays them without
executing anything. Raw reasoning, grants and approvals are not saved. A
pre-dispatch unverified attempt survives cancellation or a crash; a completed
result replaces it. Inspect files and the journal before retrying an interrupted
effect. Partial forks drop tool notes and summaries whose message boundaries
cannot be determined. Old sessions cannot recover results they never stored.
Ambiguous explicit secret assignments discard the whole note; redaction is
conservative, not proof that arbitrary prose contains no confidential data.

The status line and `/usage` report provider-reported chat input/output tokens
and requests. OpenAI requests streamed usage; Anthropic reports usage including
input cache reads/writes. Other providers may omit usage, so totals can be lower
bounds. Legacy per-session token budget and output-limit preferences are ignored;
ISyCode does not impose a local generation cap. When the history does not fit
the selected model's window, the request carries the recent messages plus a
deterministic continuity capsule instead of the older ones, and a "too long"
rejection is capsuled and sent once more ([ADR 0009](decisions/0009-continuity-capsule.md)).
The saved conversation keeps everything. `/compact` still summarizes on request.
Connection checks and external reviews are separate. Legacy session usage is
unknown; imported counters are historical data, not verified billing records.

This is the current evidence for the local coding workflow. Older milestone
checkboxes and the competitive inventory describe earlier revisions; they are
not a substitute for current tests. This change is a local daily-use increment,
not a declaration that all integrations or all M16 acceptance items are complete.

## Start and diagnose

```bash
cd /path/to/your/project
isycode doctor --json
isycode
```

`doctor` and `/doctor` inspect installed dependencies, non-secret configuration
status and workspace permissions. They make no network requests and never read
or print API key values. Installed sandbox ingredients do not by themselves
prove that the operating system allows namespaces.

Select a provider in Settings. `/check` sends one explicit, small chat request
through ProviderNetworkOwner, Workspace Authority and IsySentinel. It can consume
API quota and requires a credential (except supported local endpoints) and a
provider-host grant. Its success establishes a chat response, not tool support.
An environment variable being present does not establish remote authentication.

HTTP proxies are supported through absolute-form HTTP requests and verified-TLS
CONNECT tunnels on Python 3.10+. `NO_PROXY` is
respected for local endpoints. Cancellation closes the proxy connection, and
plaintext received after CONNECT headers is rejected before TLS.

A real minimal OpenAI API-key request was attempted on 2026-09-30 after the user configured
a key and allowed `api.openai.com`. It reached the endpoint, which returned HTTP
429 (`insufficient_quota`, `credit_balance_exhausted`). That attempt is not a successful
API-key chat. On 2026-10-04 a separate ChatGPT subscription roundtrip did complete
(NVIDIA → subscription → NVIDIA, `head_seq=4`). The subscription participant was `auto`;
its concrete model id is NOT_DEMONSTRATED. Evidence:
`docs/handoff/tools-catalog-2026-10-03.md`. Subscription login is not API-key billing.

## Work on code

Classic includes bounded workspace read/edit, saved-key/session access, Git review,
reviewed commits and exact-executable sandboxed commands when Bubblewrap/seccomp
are available. Until the folder is trusted for quiet Classic, each edit and each
sandboxed command still asks. After that trust, recoverable edits and sandboxed
commands stop asking one by one; commit, secrets, authority, undo and MCP still
ask. Security begins with grants off; use individual grants or the reviewed
coding-tool bundle. No mode enables a free shell or offers an unsandboxed fallback.

1. Use `/context` or Context → Load workspace AGENTS.md to load project guidance.
   Reads are owned and journaled. Only the root AGENTS.md is supported here; an
   arbitrary native file picker remains disabled. The file never grants access.
   It is re-read on subsequent chat turns so stale permissions/content are not
   silently reused. `/context clear` removes it.
2. Ask for a change. Review the exact diff before applying an edit.
3. Enable command permission if needed. Approve the exact test command. The
   Linux Bubblewrap/seccomp sandbox blocks network and masks sensitive paths.
4. Review `/diff` and the actual test exit status. Command side effects are not
   covered by `/undo`.

If a stream fails or is cancelled, the original prompt is kept without
overwriting a newer draft. Partial answers do not enter completed chat history.
`/retry` prepares the previous prompt for review; it does not issue a request or
repeat tools. Previous successful edits/commands remain applied and must be
inspected before resending. Automatic provider retries are intentionally absent.

## Save and resume

Recurring projects with session permissions save redacted transcripts and
non-secret provider/model/role references, root AGENTS.md provenance and a draft.
The saved context is a relative reference, not a stored instruction body.
Resume re-reads it under current permissions. Saved state never includes keys,
grants, endpoints or arbitrary imported role instructions. Explicit provider/model
environment overrides remain authoritative on resume. Legacy v1 transcripts
still load; new sessions/export use v2.

Drafts are saved after one second of inactivity and flushed on ordinary exit,
through the session owner. Persistence requires both session permissions and a
recurring workspace. Draft text is retained without automatic truncation. An abrupt crash before the
debounce save can lose the latest keystrokes. Common secret patterns are redacted;
redaction is not a guarantee that arbitrary confidential prose is safe to share.

Commands:

| Command | Result |
| --- | --- |
| `/sessions list` | Open saved conversations |
| `/sessions new` | Start an empty conversation, preserving the previous draft |
| `/sessions resume ID` | Restore conversation and its selection metadata |
| `/sessions search TEXT` | Search titles and saved messages |
| `/sessions rename TITLE` | Rename the current saved conversation |
| `/sessions fork` | Create and resume an independent copy |
| `/sessions export` | Show portable JSON with common secret patterns redacted |
| `/sessions import JSON` | Validate pasted JSON and create a new conversation |
| `/sessions delete` | Delete only the current conversation after its separate scoped grant and confirmation |

Export is displayed inside the TUI; it does not silently write a file or access
the clipboard. Review exported content before sharing. Import accepts validated
v1/v2 transcripts, strips extra message fields, and rejects credential/grant/state
fields it does not support. Deletion permission is granted from Settings →
Authority for the current conversation and is distinct from permission to save.

## Reproducible evidence

```bash
python -m pytest -q -m 'not integration' -ra
python -m pytest -q -m integration tests/test_daily_tui.py -ra
```

The second command is a local real-Bubblewrap witness, not a Gateway/provider
integration. It uses a simulated provider to ask for real owned reads and edits,
keyboard approval of the actual diff, an approved real sandboxed unittest run,
and a real Git diff. It verifies exit code 0, one executed test and a valid audit
journal. It needs a Linux host with Bubblewrap namespaces and libseccomp;
ingredient absence is a skip, namespace denial is a failure rather than a pass.

Additional full-app tests exercise 80×24, 100×30 and 140×40 terminals, multiline
entry, rail shortcuts/resize, rate-limit/server/partial-stream failures,
cancellation, draft recovery across launches, context reauthorization and
session deletion. These are headless widget checks, not a visual/accessibility
audit or a long-duration performance soak.

An additional [local long-session witness](long-session-soak-2026-10-01.md)
passed on 2026-10-01: 75 real read/edit/test/diff cycles, two restarts and deliberate
stream failures/cancellations over about 11 minutes. It found and fixed a command
startup race. Provider responses were simulated; this does not establish real
provider authentication, multi-hour performance or bounded memory.

## Visual polish (2026-10-01)

The sidebar starts hidden below 100 columns. Its Files/Overview buttons now fit
the compact rail, and the header shortens long paths from the left while keeping
the workspace indicator visible. Explicit sidebar choices survive resize at
80 columns and above; below 80 it temporarily hides, restoring that choice when
space returns. The composer, keyboard hints and navigation share one layout
container so they no longer overlap.

Read-tool outcomes have a readable summary with their journal receipt in an
expandable detail. Console search opens folded details before scrolling to a
match. Secondary text has stronger contrast. Optional integrations start folded;
an absent configuration uses a neutral OFF state while errors remain distinct.
Settings prioritizes defaults, authority, credentials, journal and workspace
controls; optional connections are grouped under Integrations. Reasoning durations
under one second display `<1s`. These changes were visually inspected through
fresh Textual exports at 140×40, 100×30 and 80×24, using a local monospace font.
Actual terminal font rendering and assistive-technology support remain separate
validation work.

The final local Python 3.10 suite passed 817 tests (3 skipped, 11 external
integration cases deselected). Focused layout/scroll/workflow tests also passed
on Python 3.12. Regression coverage includes real Files-tab clicking at 80×24,
Unicode/long-path headers with the sidebar open, searchable folded receipts,
submenu return navigation, and non-overlapping composer hints. The startup
dialog test caught a pending header refresh looking in the active modal rather
than the header's containing screen; that lookup was corrected before the final
suite run.

## Still outstanding

- Gateway live semantic operation, with a local grant, remote scope and matching
  workspace id: NOT_DEMONSTRATED. No Gateway write or Bridge daemon was started.
- Tailscale tailnet connectivity, Mobile Host remote sessions/streaming/approvals,
  Windows paths, a live local MCP server and native Claude remain NOT_DEMONSTRATED.
  Their owners and offline tests stay in place.
- The 2026-10-04 clipboard witness is this X11 desktop and `xclip` only
  (`docs/evidence/clipboard-witness-2026-10-04.json`). Wayland and Windows clipboard
  tools were not run.
- Multi-hour performance/memory validation and interactive terminal/accessibility
  review remain release acceptance work; the recorded local soak is one bounded
  scenario, not a broad performance claim.
- MCP remote transports/OAuth, additional LSP features, product Bridge inside
  Secure and OpenISy L0/L1 remain follow-up integrations. Web search does not exist;
  webfetch reads one public HTTPS page and does not search.
- Verified monetary cost estimates and automatic retry policies remain future work.
  Existing ownership/security gates stay in force.

## Verification record (2026-09-30)

The local suite passed 605 tests, skipped 3 optional checks and deselected 11 external integration cases. The focused real-Bubblewrap TUI workflow passed separately (1 test). An unrestricted test collection also exposed five existing external Bridge/broker failures because the separate ISyCo checkout and services are absent; the documented local command excludes that integration marker. Optional Anthropic SDK and Pyright checks remain skipped.

## Sibling folders and automatic file edits

Files → Folders (also available in Settings) adds up to eight direct sibling
project directories using short aliases such as `other-project`. Absolute paths
with spaces are supported. Each folder gets its own exact-root read/search grant
and, if selected, write grant. File tools choose `folder`; omitting it uses
`main`. The browser can switch folders without changing the primary project,
provider/session authority or command working directory. Read-only attachments
remain read-only even if the other project uses Classic mode. Commands, Git,
deletes and moves still operate only on the primary project. Removing an
attachment removes this chat's access, keeping files and standalone grants.
Hidden directories, symlinks, shared parents, children and the private ISyCode
state are rejected. Keep ISYCODE_STATE_HOME outside project roots.

Every proposed file creation/edit opens its actual folder and exact diff by
default. **Always allow…** opens a separate danger warning, initially focused on
Cancel. Confirming enables automatic file creation/editing for that folder and
persists for that primary workspace. Files → Folders shows ON/OFF and disables
it immediately. Model mistakes or malicious file instructions can overwrite
work without individual review; keep backups and inspect Git diffs. ISySentinel,
Authority, sensitive-path protections, immutable request approvals, checkpoints
and per-root journals still run for each action. They do not guarantee that an
allowed edit is correct. Commands/deletes/moves/commits retain their own prompts.
Tool results label `approval_mode` as `reviewed` or `delegated`; automatic edits
are never reported as individually reviewed. Removing/readding or replacing an
attachment invalidates pending diff and warning confirmations.

Verification for this increment: Python 3.10 local CI suite **844 passed, 3
skipped, 11 integration cases deselected**; separate real Linux sandbox coding
workflow **1 passed**. Root-aware approval/registry/coverage checks **49 passed**
on Python 3.10. Native controls were captured at 80×24 and 60×18, with default
Cancel and visible pinned buttons. Provider replies in the coding fixture were
simulated; files, approvals, journals, sandbox command and Git diff were real.
Independent review found no remaining critical/important blockers after fixing
private-state access and stale registration confirmations.


## Classic coding defaults (2026-10-02)

Classic now supports the common daily loop without a setup grant per tool: read/edit,
Git status/diff/approved commits and Bubblewrap/seccomp commands when available.
Per-action previews and approvals, IsySentinel and the journal remain mandatory;
explicitly disabled grants still override the preset. Security remains opt-in by
capability and offers the same tools through individual grants or the bundled
coding-tool setup. The local Python 3.12 run passed 1,053 tests with 7 skips; compileall and the focused
security/mode regression set (101 tests) also passed.
