# Native platform parity: storage and Git

ISyCode keeps one source tree. Native storage, recovery effects and Git discovery are selected at composition boundaries; product owners continue to enforce Workspace Authority, IsySentinel, approvals and receipts.

This is an incremental implementation of the reusable CrossPlatform-Parity method (initial method commit `27d8ef2`). No runtime imports or dependencies connect the repositories.

## Implemented boundaries

| Boundary | POSIX | Windows |
| --- | --- | --- |
| Private state locks | flock with thread reentry guarded | Native byte lock with thread reentry guarded |
| Ownership and privacy | UID and permission bits | Owner SID and user/SYSTEM DACL |
| State creation | Private directory modes; linked parents refused | Private creation DACL; junction/reparse parents refused |
| State replacement | File flush, atomic replace and directory fsync | File flush and write-through native rename |
| Iteration deletion | Descriptor-pinned unlink with nonblocking lock | Exclusive native handle and deletion on handle close |
| Recovery preimages | Descriptor-relative filesystem operations | Handle-verified reads and replacement with late preimage checks |
| Git discovery | Existing system-bin discovery | HKLM installation discovery, native binary and dependency-tree ACL validation |

Callers share a typed storage contract. OS branches live in composition/adapters. Existing POSIX effect code was moved intact to its adapter rather than cloning the product source.

Windows requires `pywin32`, installed only under its platform dependency marker. Git must be an admin-installed Git for Windows distribution with verified ACLs; untrusted PATH/cwd and per-user writable installations are not accepted automatically.

Integrity-pinned bundled resources keep their committed bytes through `.gitattributes`, including Windows checkouts. Manifest acceptance hashes were not changed. Legacy POSIX transcripts remain readable under a private parent directory; Windows checks the file DACL as well because traversal permission alone is insufficient.

## Integration

The effect ledger, operation journal, private action journal, iteration owner, chat-session locks and workspace grant policy consume native storage. Action audit rotation uses a stable sidecar lock, including across replacement of the active journal. Byte-oriented descriptors use binary mode on Windows, preserving hash-chain bytes.

Windows recovery refuses edits arriving during the temporary file flush. The shared VerifiedFS replacement also rechecks the preimage after flushing. Same-user directory rename races in the final replacement interval remain a documented limitation; no universal compare-and-swap or hardware power-loss guarantee is claimed.

See [the human guide](GUIA.md), [implementation plan](PLAN.md), [verification report](REPORT.md) and [remaining capability inventory](INVENTORY.md).

## Limits

The native Windows LPAC/Job command sandbox and fixed-VHD provider are implemented behind NATIVE_ACCEPTED=False. Real VHD controls and approved Unicode promotion are recorded in REPORT.md; broader acceptance still gates product activation. Command execution remains unavailable by default; no unrestricted-shell fallback was added. Live model services, packaged EXE behavior, physical clipboard roundtrip and complete native Windows product parity are not certified by these changes. Optional integrations and additional private-state stores still need individual inventory and acceptance.

Existing unsafe state is refused rather than silently treated as authentic. The effect ledger may tighten an existing directory owned by the current user; file contents and grants are not automatically migrated or trusted. Use an isolated fresh state directory for initial Windows verification and preserve existing state for explicit review.

The native-contract CI matrix covers Linux and Windows. Existing full Linux CI remains in place. Adding a workflow is not evidence that GitHub ran it; local evidence is recorded separately.
