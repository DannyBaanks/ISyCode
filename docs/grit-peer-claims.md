# Peer claims from grit (advisory, opt-in)

ISyCode can show which functions other AI agents have locked in this
workspace before you approve an edit. The lock registry comes from
[grit](https://github.com/rtk-ai/grit) (Apache-2.0, by RTK AI) — an external
tool ISyCo agents may run in parallel on the same codebase. ISyCode **only
reads** that registry; it never claims, creates worktrees, merges, or writes
anything through grit, and the note never blocks or authorizes a change.
It is coordination data, the same way a Bridge lease is a traffic light and
not a permission.

Credit: peer-claim coordination data is produced by
[grit](https://github.com/rtk-ai/grit) (Apache-2.0). ISyCode does not vendor
or redistribute grit and does not claim its behavior as its own.

## How to turn it on

Everything is off until all of these are true:

1. The `grit` binary is installed and on `PATH` (for example
   `cargo install --git https://github.com/rtk-ai/grit`).
2. You ran `grit init` inside the workspace root, creating the `.grit/`
   registry. Not running `grit init` keeps the feature completely inactive.
3. The workspace grants `grit.claims.read` (Settings · Authority) with the
   sandbox executable, plus the usual `workspace.files.read` grant for the
   root. Classic mode does not imply either grant.
4. `bwrap` (bubblewrap) and `libseccomp` are available, like the LSP
   adapters.

## What you see

* On a write approval card, a muted line such as:
  `Peer claims (grit, advisory only): login held by agent-1 (add validation)`.
* In the model's tool result, the same text as `peer_advisory`, so the
  assistant can choose a different file or symbol instead.
* Every read is journaled with a receipt that records the pinned binary
  digest and the digest of the raw `grit status` output.

## How it runs

The pinned binary (path + SHA-256 recorded at discovery, re-checked on every
read) executes `grit status` inside the same sandbox profile as the LSP
adapters: bubblewrap with no network content, a seccomp socket-deny list, no
home directory, the workspace mounted read-only. Only `.grit/` stays
writable, because SQLite opens its registry in WAL mode and must write
`-wal`/`-shm` sidecar files even for readers. Output is parsed against the
exact grammar of the pinned build; any unknown line, non-zero exit, timeout
or oversize output makes the advisory read *unavailable* — it is never
shown as "no claims". `NO_COLOR=1` keeps the output free of ANSI sequences.

## Evaluation notes (2026-10-09, grit 0.4.0)

Verified on a toy Python repository and on a clone of this repository:

* `grit init` indexed 4,773 symbols and 17,176 dependency edges from the
  ISyCode tree in about 1.5 s; Python classes and methods parse correctly.
* Two agents claiming different symbols of the same file both succeed; a
  contested symbol is blocked with the holder's identity and exit code 1.
* The full `claim → edit in worktree → done` flow rebases and merges
  serially, removes the worktree and releases the locks. With a dirty main
  checkout the merge is refused (exit 1) and the agent branch is preserved.
* Sandboxed `grit status` fails with a fully read-only workspace ("unable
  to open database file") and succeeds with only `.grit` writable — hence
  the mount profile above.

Known upstream caveats (reasons this stays advisory-only for now):

1. `grit status` prints every lock as `[EXPIRED]` immediately: it parses
   SQLite's `datetime('now')` timestamp as RFC-3339 and fails. Functional
   expiry (SQL `julianday`) is correct; ISyCode ignores the expiry field.
2. Method symbols are file-scoped, not class-qualified: two classes with a
   same-named method in one file collapse into one `file::name` symbol.
3. Re-running `grit init` indexes grit's own `.grit/worktrees/` copies,
   inflating the symbol registry until the next clean re-index.
4. There is no machine-readable output mode (`--json`); ISyCode parses the
   pinned text grammar of the exact binary it hashed.
5. `grit done` releases the locks even when it skips the merge because the
   main checkout is dirty; the agent branch is kept for manual recovery.

ISyCode does not expose `grit claim`/`grit done` (or worktree creation)
because they mutate the repository and would bypass ISyCode's approved-commit
model. A future milestone could add opt-in claim/release actions behind the
same gates if multi-agent dogfooding wants them.
