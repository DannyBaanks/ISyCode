# Authority, tools and optional integrations

ISyCode runs each effect through its execution owner, workspace authority and
IsySentinel decision, then records the outcome. IsySentinel decides; it does
not execute actions. Credentials, roles, injected context and discovered
services are not grants.

## Workspace and modes

`launch_dir` is where the application was invoked. `workspace_root` is the
logical boundary selected by `.isyroot`, or the launch directory when no
marker exists. The marker never grants access. Workspace Authority owns the
effective capabilities within that boundary.

Choose modes at onboarding or under Settings → Permissions → Authority &
Security. My defaults affects new-workspace preferences, not existing grants.

| Capability | Classic | Security |
| --- | --- | --- |
| Read/search files | Coding preset | Explicit grant |
| Edit files | Coding preset; ordinary edits can be quiet after explicit folder trust | Explicit grant and applicable review |
| Chat with selected provider | Coding preset | Explicit grant |
| Save conversations | Coding preset | Explicit grant |
| Store/remove credentials | Service permission and confirmation | Explicit service permission and confirmation |
| Git status/diff | Coding preset | Explicit grant |
| Git commit | Permission plus exact commit approval | Permission plus exact commit approval |
| Sandboxed commands | Available when isolation exists; quiet after explicit trust | Explicit grant and applicable review |
| MCP/diagnostics | Separate permission | Separate permission |
| Gateway, Tailscale, Mobile Host, Bridge | Separate permission | Separate permission |
| Delete/move files | Coding preset; quiet behavior requires explicit trust | Explicit permission and applicable review |

Classic is not a bypass. Before folder trust, edits and commands retain their
exact per-action approval. Trust does not turn on integrations, approve commits
or secrets, or allow unrestricted commands. A moved/copied folder does not
inherit trust. Explicit denials remain effective.

Turn on all coding tools grants the listed local coding capabilities, including
clipboard copying and diagnostics. It does not remove confirmations or provide
a sandbox where none exists. See the [security boundaries](../design/isysentinel-security-boundaries.md)
and [evolution gates](../roadmap-classic-security-ux.md) before changing policy.

## Tool surface

Tools are exposed according to permissions and model support. The model
requests a tool; an owner performs the permitted action and returns a verified
outcome. Missing permissions produce guidance rather than an unrestricted
fallback.

| Tools | Permission/review |
| --- | --- |
| `workspace_list`, `workspace_read`, `workspace_search`, `workspace_grep` | Workspace read/search permission |
| `workspace_pack` | Read/search plus context-package review |
| `memory_*`, `memoir_*` | Workspace-tool access plus review for each operation |
| `workspace_edit`, `workspace_write` | Edit permission and applicable folder/action approval |
| `workspace_delete`, `workspace_move` | Edit permission and applicable folder/action approval |
| `/undo` | Edit permission and inverse-diff review |
| `workspace_run`, `/run` | Sandbox command permission and applicable command approval |
| `git_status`, `git_diff` | Git review permission |
| `git_commit`, `/commit` | Commit permission and exact file/message/diff review |
| `webfetch` | Public HTTPS destination permission; review for each new host |
| `mcp__<server>__<tool>` | Server-start permission and review of each tool call |
| Automatic Python diagnostics | Separate diagnostic permission |
| `update_tasks` | Local task planning; no effect permission |
| Mouse selection/explicit clipboard controls | Clipboard permission; user-only path |

`workspace_pack` limits context to 32 paths, 200 files and 1 MiB. Individual
reads remain capped at 128 KiB. It skips secrets, hidden entries during directory
walks and common build/cache directories. Its local estimate is approximately
two bytes per token, not the provider tokenizer. Packed content is untrusted
data.

Memory uses private SQLite state outside the checkout, separated by workspace.
The agent uses it on request. Forgetting deletes the selected memory;
consolidation archives it. Approved reads can enter model context and must be
treated as untrusted data.

## Files, sandbox and Git

Fragment edits require a unique match. Matching can account for line endings,
trailing whitespace and indentation; approval still displays the exact diff.
Writes are atomic, reject symlink traversal and remain capped at 128 KiB.
Changes since review prevent overwriting. ISyCode file edits retain checkpoints
for `/undo`; arbitrary command effects are not covered by that undo path.

Linux command isolation uses bubblewrap, libseccomp and Python. It has no shell
or network access, restricts writes to the workspace and keeps `.isyroot`
read-only. Default timeout is 120 seconds, maximum 600 seconds; output is capped
at 64 KiB. Missing isolation leaves execution unavailable.

Git operations disable hooks/system configuration and do not implicitly push.
`git.push` is a separate action bound to an HTTPS remote, ref and exact digest.
Configurations that would execute additional programs are rejected. Git must
be rooted at the workspace. Optional grit conflict notices are informational,
not locks or permissions.

Approvals are single-use and bound to the request digest. The private journal
stores chained decisions/receipts in 4 MB segments and detects missing,
reordered or modified segments. Clipboard records contain size/digest, not the
copied text. Source scanner coverage is not a live-service witness or release
approval; see [verification](verification.md).

## Optional integrations

- **MCP local:** user configuration lives in `~/.config/isycode/mcp.json`.
  Starting a server runs a program as your user and reviews the exact command;
  each tool call reviews its arguments. Descriptions/results are untrusted.
  The pinned Playwright path is limited to `browser_snapshot`: you navigate,
  review the filtered accessibility text, then decide whether to share it.
  Output is capped at 24,000 characters; fidelity is not certified. It does
  not operate your personal Chrome profile.
- **RTK:** optional [rtk-ai/rtk](https://github.com/rtk-ai/rtk), Apache-2.0.
  Compresses output from an already-approved original argv executed once.
  Compression does not grant authority; original output remains retrievable
  by digest. See the [RTK guide](../rtk/GUIA.md).
- **Skills:** packaged guidance is pinned by digest. Reading instructions
  does not execute scripts or add grants. The authoring Design Skills are
  separate from the application's pinned runtime skill bundle.
- **LSP:** local availability appears in the interface. Pyright supplies
  post-edit Python diagnostics with separate permission. Other server
  handshakes and their platform/runtime availability require their own evidence.
- **Multi Harness:** read-only inspection of Crush, Qwen Code, OpenCode,
  Claude Code, Codex, Grok, Hermes, fx, OpenClaw, Pi, Kimi, Cursor, Copilot,
  Command Code and Kilo CLI. Copying defaults/importing transcripts requires
  confirmation; discovery does not execute another agent.
- **ISyCo Gateway:** requires `GATEWAY_URL`, the appropriate remote key/scope
  (`isyco.semantic`), matching opaque IDs and local permission. Non-loopback
  destinations require HTTPS. Local authority/Sentinel and the remote
  perimeter both apply. Live permitted semantic operation remains
  NOT_DEMONSTRATED in the referenced readiness evidence.
- **Tailscale/Mobile Host:** optional private Serve `/isycode` to loopback
  port 8765, never Funnel. Pairing uses a one-use PIN. Remote sessions,
  streaming and approvals need independent live validation. See
  [Mobile Host v1](../mobile-host-v1.md).
- **IsyMotron:** optional planner for `/plan`, not the security authority.
- **OpenISy:** external discovery catalog when `OPENISY_API_URL` is configured;
  discovering providers, MCPs or Skills does not activate them.
- **Bridge:** opt-in peer coordination. A lease is a traffic signal, not
  action permission. ISyCode does not start its daemon.

Service configuration, implementation presence and fixture tests must not be
presented as equivalent to a live end-to-end witness.
