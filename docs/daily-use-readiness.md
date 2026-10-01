# Daily-use readiness — updated 2026-10-01

## Continuity, compatibility and reported consumption

The package now pins Textual 1.0.0, validated with Python 3.10 and 3.12.
Historical Textual 8.2.8 screenshots do not establish support for that version.
Chat shows model steps and tools in order and follows the bottom while preserving
manual history/search navigation.

New sessions retain up to 32 tool notes, each with at most 2,000 argument and
4,000 result characters. At most 16,000 characters of recent notes are supplied
as explicitly untrusted, potentially stale context on the next turn. Resume
displays them without executing anything. Raw reasoning, grants and approvals
are not saved. A pre-dispatch unverified attempt survives cancellation or a
crash; a completed result replaces it. Inspect files and the journal before
retrying an interrupted effect. Partial forks drop tool notes and summaries
whose message boundaries cannot be determined. Old sessions cannot recover
results they never stored. Ambiguous explicit secret assignments discard the
whole note; this is conservative redaction, not proof that arbitrary prose
contains no confidential data.

The status line and `/usage` report chat/compaction input/output tokens and
requests. OpenAI requests streamed usage; Anthropic reports actual usage,
including input cache reads/writes, and respects the requested output limit.
Other providers may omit usage: reported totals then remain lower bounds.
Settings → My defaults offers an optional per-session budget of 10,000, 50,000,
100,000 or 500,000 tokens, off by default. It blocks subsequent requests when
reported consumption reaches the budget or consumption is unknown, and reduces
the next output limit to the known remainder. Input tokens and an in-flight
request can exceed the budget; it is not a billing cap. Connection checks and
external reviews are separate. Legacy sessions without usage are unknown;
imported counters are historical data, not verified provider billing records.

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

A real minimal OpenAI request was attempted on 2026-09-30 after the user configured
a key and allowed `api.openai.com`. It reached the endpoint, which returned HTTP
429 (`insufficient_quota`, `credit_balance_exhausted`). No successful live chat or
live coding workflow is claimed. ChatGPT subscription login is a separate
integration from API-key billing and is not implemented by this increment.

## Work on code

Classic includes bounded workspace read/edit, saved-key access and saved-session
permissions for a recurring project. Security requires explicit grants.
Commands require a separate executable grant and approval in either mode.

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
recurring workspace. At most 16,000 characters are retained on disk; longer text
remains in the composer and the UI reports the limit. An abrupt crash before the
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
the clipboard. Review exported content before sharing. Import accepts bounded
v1/v2 transcripts, strips extra message fields, and rejects credential/grant/state
fields it does not support. Deletion permission is granted from Settings →
Authority for the current conversation and is distinct from permission to save.

## Reproducible evidence

```bash
python -m pytest -q -m 'not integration' -ra
python -m pytest -q -m integration test_daily_tui.py -ra
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

- The user chose offline validation. A real provider turn with tool calls,
  authentication failures and quota behavior remains unverified in this environment.
- Gateway public-origin and approved semantic-query witnesses remain separate
  remote milestones. No Gateway write or Bridge daemon was started.
- Multi-hour performance/memory validation and interactive terminal/accessibility
  review remain release acceptance work; the recorded local soak is one bounded
  scenario, not a broad performance claim.
- MCP remote transports/OAuth, additional LSP features, Mobile Host runtime
  sessions, Bridge and L1 remain optional follow-up integrations.
- Verified monetary cost estimates, automatic retry policies and portable file/clipboard
  transfer UI remain future work. Existing ownership/security gates stay in force.

## Verification record (2026-09-30)

The local suite passed 605 tests, skipped 3 optional checks and deselected 11 external integration cases. The focused real-Bubblewrap TUI workflow passed separately (1 test). An unrestricted test collection also exposed five existing external Bridge/broker failures because the separate ISyCo checkout and services are absent; the documented local command excludes that integration marker. Optional Anthropic SDK and Pyright checks remain skipped.
