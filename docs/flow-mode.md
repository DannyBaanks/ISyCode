# Flow

Flow is the third workspace mode defined by [ADR 0010](decisions/0010-flow-mode.md).
Choose **Settings → Workflow → Flow**, or choose Flow in custom onboarding.
Classic remains the recommended onboarding choice and Quick Start default.
Changing modes requires a human confirmation; the model cannot do it.

Flow can read, edit, move, delete and run sandboxed shell commands without a
question for each recoverable local action. Sentinel, Workspace Authority,
explicit denials, the cumulative effect ledger and receipts still apply.
Commands require a verified native sandbox and have no network. On platforms
without that backend they fail closed, with no execution on the host.
Flow also masks every multiply linked regular file from command reads because
its other links could expose data outside the workspace. Classic keeps its
existing sensitive-inode masking behavior.

Every chat turn opens its own private recovery record before contacting the
provider. A storage failure prevents the turn from starting and keeps the
prompt. Only one Flow turn can record a workspace at a time. Provider retries
within the same turn share the record; an explicit `/resume` starts a new
recoverable segment and preserves the existing no-replay rule for tools.
Cancellation waits for an already executing file mutation to settle before
closing its record. Completed file effects remain recoverable even when the
provider fails or the turn is stopped.

After a turn, the conversation lists its changed paths. `/undo` restores the
newest recorded turn that still has changes, including after restarting the
app. Repeating `/undo` moves to the preceding turn. Later human changes to
bytes or permission bits are reported as conflicts and preserved. Corrupt
records stop recovery instead of silently selecting an older turn. Undo does
not remove Git commits: it restores the working files and leaves history
intact. To undo Flow work after switching to another mode, select Flow again.
Classic and Security retain their existing single-change undo behavior.

Flow commits run without a review only when every selected path belongs to
the current turn, its preimage matched HEAD, its current bytes still match
what the turn wrote, and there are no staged changes for those paths. Other
commits require the usual review. Push, credentials, provider/configuration,
authority changes and integrations keep their own permissions and approvals.
Changing modes cancels the active turn with confirmation, invalidates pending
approvals and clears in-memory automatic-edit permissions without clearing the
conversation.

The current recovery limits are 256 MiB of preimages and 4,000 paths per turn,
with 20 retained turn directories per workspace. An exhausted record prevents
further changes from landing quietly. There is no session network permission
in Flow v1; that remains MF.v2 work under D1.

## Verification and release status

The implementation is a candidate for gate GF in the
[Classic/Security roadmap](roadmap-classic-security-ux.md#mf--flow-tercer-modo-sin-preguntas-repetitivas).
Tests include real Linux bubblewrap isolation, file round trips and conflicts,
staged-work attribution, mode-switch revocation, cancellation during a worker
thread mutation, durable recovery after restarting the TUI, and onboarding and
Settings in en/es/zh at 80×24, 100×30 and 140×40.

Textual screenshots and a simulated provider demonstrate the tested UI paths;
they do not certify a physical terminal, live inference or native Windows/macOS
execution. GF requires independent acceptance tied to the evaluated SHA.
Completing this implementation does not approve GF, M9, M10 or a release.
