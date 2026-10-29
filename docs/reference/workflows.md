# Workflows, providers and commands

This reference describes the local source accompanying the product README.
See [verification](verification.md) for the distinction between implemented
behavior, fixtures and live service evidence.

## Interface

The idle landscape and cat give way to chat as work begins. The header shows
the project and mode; the model line shows configured provider status. A Ready
configuration label is not evidence that inference against that service ran.

- **Composer:** Enter sends, Ctrl+J inserts a newline. Shift+Enter/Alt+Enter
  also work where the terminal delivers those key combinations. Ctrl+S
  switches Idea Box/ShellBox. The context meter summarizes available space.
- **Overview:** flat sections for IsySentinel, MCPs, LSPs, Skills, Connections
  and workspace state. Discovery does not grant or invoke an integration.
- **Files:** navigate directories, search paths, inspect readable files, copy
  a path or open a full preview. Enumeration and reading use Authority,
  Sentinel and verified owner receipts. Files does not delete or rename.
- **Settings:** Conversation, Preferences, Permissions and Connections.
  Search spans categories; row selection previews details. Enter opens an
  option. Available `?` help explains the selected setting.
- **Approvals:** review the exact diff/command and accept or reject. Rejection
  is the default. A rejected effect is not rendered as a successful action.

## Text selection and copying

Focus an expandable content box and press Space to expand/collapse it. Space
typed inside an editable text input remains text input. Double-clicking a box
opens a copy menu with separate selection and whole-box choices.

Dragging selects text without copying it. Ctrl+C copies only the marked range,
including its selected whitespace and logical newlines. Selecting two lines
copies those lines, not the whole output. Whole-box copying requires choosing
that explicit option. With no selection, the selection option is unavailable.
The clipboard permission and owner path still apply; the model has no clipboard
tool and does not receive the copied text.

See the [gesture guide](../design/2026-10-11-tui-implementation/GUIA.md).

## Sessions and continuity

Saved conversations retain their transcript, pending messages and turn state.
Switching chats parks the active lane without cancelling it; Esc stops the
visible lane. Up to eight messages can wait in the current queue. Sending an
empty input over a queue steers the active turn.

Two processes editing the same conversation compare its loaded fingerprint.
When another process saved changes, choose fork, reload or continue without
saving rather than overwriting that transcript. Locking uses `flock` on Linux
and macOS; native Windows behavior needs separate validation.

Interrupted streams can retry their provider step without re-running a tool
that already executed. Fixed delays and bounded Retry-After handling apply;
Esc cancels the wait. After retries are exhausted, the prompt remains available
and `/retry` continues. See [ADR 0008](../decisions/0008-automatic-continuity-recovery.md).

The [continuity capsule](../decisions/0009-continuity-capsule.md) summarizes
requests, tasks, idea-box notes, changes, commands and reads locally. It helps
with context overflow, smaller models and subagent launch without trimming the
saved conversation. `/compact` requests a model summary. `@path/to/file`
attaches up to five files through the read-permission path, as untrusted data.

There is no fixed local tool-step limit. Esc can stop the turn. Scroll follows
new output when at the bottom; scrolling up retains your position and End
returns to the tail.

## Providers and models

Select provider → model → supported reasoning settings. Environment variables
`ISYCODE_PROVIDER` and `ISYCODE_MODEL` are also available. Saved model selection
survives restarts and takes precedence over catalog defaults.

| Provider path | Credential/configuration |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic native | `ANTHROPIC_API_KEY`; install the optional Anthropic extra |
| NVIDIA NIM | `NVIDIA_NIM_API_KEY` |
| Nebius | `NEBIUS_API_KEY` |
| Groq | `GROQ_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY`; explicit tool-call opt-in where required |
| Ollama / llama.cpp | Local endpoint configuration; credentials may be optional |
| ChatGPT / Codex | Official browser/device-code sign-in, distinct from an API key |

A masked field can request a missing key. Named credentials are managed under
Settings → Permissions. Keyring storage and removal require their own review;
a credential does not authorize network access. A remote provider processes
the context sent to it; local-first session storage does not make remote
inference offline.

Model details show known context/family/tool/pricing/availability metadata and
its source. Missing facts stay Not reported. Catalog entries and featured
models are snapshots; their presence does not prove account availability or
live service validation. Presets without declared tool-call support only chat
unless explicitly enabled with `ISYCODE_TOOL_CALLS=1`.

## Language

The interface cycles es → en → zh in Settings. Product names and protocol
commands remain unchanged. Chat, code and provider output are not automatically
translated. Catalogs live at `src/isycode/locales/<code>/LC_MESSAGES/isycode.po`.
Some chrome, including the composer placeholder, can remain in English;
complete translation coverage is not asserted.

## Slash commands

`/` or Ctrl+P opens command navigation; `/help` lists commands. Names remain
in English in every interface language.

| Commands | Purpose |
| --- | --- |
| `/undo` | Review and undo the latest ISyCode file change |
| `/run <program> [args]` | Request a sandboxed command |
| `/git`, `/diff`, `/commit` | Inspect Git and review a commit |
| `/mcp add playwright`, `/mcp add context7`, `/mcp start <name>` | Configure/start pinned MCP paths with separate approvals |
| `/compact`, `/retry` | Summarize or continue an interrupted prompt |
| `/rtk`, `/rtk recall <sha256>` | Opt-in compression and original-output retrieval |
| `/harness` | Inspect Multi Harness |
| `/providers`, `/models` | Select providers and inspect models |
| `/session`, `/sessions`, `/msg <name> <text>` | Inspect/switch conversations or deliver a message to another lane |
| `/skills`, `/subagent`, `/iteration` | Select guidance, start a subagent or sequence three models |
| `/doctor`, `/check`, `/usage`, `/context` | Local diagnostics, provider probe, usage and context |
| `/readme`, `/plan`, `/review` | README preview, optional planner and external-review paths |

Custom commands are prompts loaded first from
`~/.config/isycode/commands/<name>.md`, then `.isycode/commands/`. They do not
grant capabilities. Commands that contact services need their separate
configuration and permission.

## Keyboard reference

| Input | Action |
| --- | --- |
| Enter / Ctrl+J | Send / newline |
| Esc | Stop the visible turn, go back or close |
| Ctrl+S | Idea Box / ShellBox |
| `/` / Ctrl+P | Command navigation |
| Ctrl+F / Ctrl+Shift+F | Search current chat / saved conversations |
| Ctrl+B | Toggle sidebar |
| F6 / Shift+F6 | Files / Overview |
| F7 / Shift+F7 | Adjust sidebar width |
| Ctrl+L | Return to composer |
| Ctrl+T | Fold Tasks |
| `y` / `n` | Approve / reject when reviewing an action |
| `?` | Explain supported Settings options |
| Space on a focused content box | Expand/collapse |
| Double-click on a content box | Open copy choices |
| Mouse selection + Ctrl+C | Copy exactly the selected range |

Terminal key delivery and glyph rendering can vary. The terminal controls
font/size; Settings controls high contrast, Unicode/ASCII and reduced motion.
