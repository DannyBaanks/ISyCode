# Daily TUI readiness implementation plan

**Goal:** Close the six local daily-use gaps identified with the user, then commit and push (create a PR if the GitHub API is available). Live provider validation was later authorized: OpenAI responded HTTP429 insufficient_quota/credit_balance_exhausted; successful live workflow remains pending.

**Architecture:** Keep Textual and existing execution owners. All workspace reads, transcript changes, provider requests and session deletion retain Authority, Sentinel, journaling and approvals. Portable sessions contain only non-secret selection metadata and relative context references, never credentials or grants.

**Constraints:** Existing checkout is isolated; no worktree. Preserve unrelated changes. Include the previously authorized startup/shortcut fix. No Bridge daemon, external Gateway writes, VPN changes or provider calls without configuration.

## Tasks

- [x] Recovery: retain original prompts on failure/cancellation, manual `/retry` prepares a draft rather than replaying tool effects; test network failures and partial streams.
- [x] Sessions: versioned provider/model/role/context references; owner-mediated rename/fork/export/import; resume re-reads context through its owner; test legacy compatibility, invalid/secret metadata and revocation.
- [x] Context: `/context` reads only root-relative AGENTS.md via LocalWorkspaceReadOwner and displays provenance; no desktop picker or permission expansion.
- [x] Diagnosis: local `isycode doctor` and `/doctor` report dependency/configuration/permission state with no credential values or implicit network calls; provider connectivity uses an explicit owned `/check` request.
- [x] Ergonomics: full-app narrow/wide startup, shortcuts, multiline input, resize and recovery tests. Fix collisions exposed by real widgets.
- [x] Workflow: exercise typed read/edit/test/diff through real owners in temporary data; attempt real Bubblewrap without weakening it; document unsupported host capability separately.
- [x] Evidence: run offline suite, reconcile roadmap/matrix and regenerate authority snapshot when line positions change. Review diff, commit, push branch, open PR.

## Review focus

Malformed imports must not leave empty sessions. Import must not restore grants, credentials, endpoints or arbitrary role instructions. Retry must not repeat a write/command automatically. Environment overrides must remain authoritative on resume. Diagnostics must not print keys or credential-bearing endpoints. A failed journal or revoked permission must stop session reads/writes. Headless TUI tests must exercise actual widgets rather than mirror their implementation.

Review resolved session default-model, preflight cancellation, redacted imports, deletion reset, check request binding, proxy bypass and CONNECT plaintext injection findings.
