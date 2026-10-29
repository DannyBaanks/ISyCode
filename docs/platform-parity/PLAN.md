# Platform parity implementation

Goal: one ISyCode source tree with native storage adapters and unchanged owner/Authority/Sentinel semantics.

Approved design: CrossPlatform-Parity architecture and contracts, agreed in the current session. Implementation is inline, capability by capability. Windows must not acquire an unrestricted-shell fallback. Linux behavior must have regression evidence from a Linux runtime; container evidence is distinct from physical Linux terminal evidence.

## Tasks

- [x] Native storage contract: `lock(fd, blocking=True)`, `unlock(fd)`, `protect(path)`, `private(path, fd=None)`, `ensure_directory(path)`. POSIX keeps flock/UID/modes. Windows uses native byte locks and protected DACLs restricted to the current user and SYSTEM. Dependencies are selected in composition, never by callers.
- [x] Tests: two-process exclusion, nonblocking refusal, release on death, binary/Unicode persistence, broad ACL refusal, junction refusal, state directory creation.
- [x] Integrate effect ledger, operation journal, iteration and session directory locks. Preserve identity and stale-state checks. Detect unsupported platforms at the composition boundary.
- [x] Journal locking and binary descriptor handling; verify audit hash chains and session restart flows on Windows and Linux.
- [x] Inventory remaining capabilities and add native CI coverage with declared unsupported requirements. Do not label partial storage support as full platform parity.
- [x] Human guide, raw test logs and hashes. Sandbox must have its own security design and adversarial acceptance before activation.

Review focus: offset changes around Windows locks; mandatory byte locking interacting with reads; ACL inheritance; existing unsafe state; deletion with an open Windows handle. These cases require tests, not silent fallback.
