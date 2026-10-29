# Independent read-only review — 2026-10-14

Reviewer: `/root/windows_sandbox_review`. Active repository only; no reviewer
edits. Final scope is a disabled prototype, not native product acceptance.

Findings and rulings:

- Windows drive/ADS/device cwd aliases: rejected by adapter path validation;
  native owner regression controls pass.
- Cleanup after committed promotion: report NOT_VERIFIABLE with committed
  ledger state; no success receipt. Profile failure still erases copied data
  and retains private ownership metadata for retry.
- Crash between copying/profile creation and ownership metadata: durable
  ALLOCATED record now precedes both; real creator-death controls pass.
- Creation before Job assignment: Job is supplied atomically through the
  CreateProcess attribute list, with a suspended process and containment witness.
- Shared staging junction disclosure: reproduced using seeded external data;
  `winfs.is_link` now refuses the source junction before copying.
- Missing POSIX compatibility exports and timeout constant: failed Linux logs
  retained. Final non-root Linux selection: 77 passed, 3 Windows-only skips.
- Execution file budget: unresolved. Native CPython wrote 513 MiB successfully;
  `NATIVE_ACCEPTED=False` remains. Initial copying budgets and free-space
  preflight are not an execution quota.

The final reviewer reported no additional blocker for conserving this disabled
prototype after restoring the POSIX timeout import. This is scoped review,
not a proof that every escape or platform behavior has been tested. Storage
containment, wider IPC/device/IPv6 controls and runtime distribution acceptance
remain NOT_DEMONSTRATED. Raw test selections and hashes accompany this record.
