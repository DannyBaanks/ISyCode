# Bounded Windows execution storage — proposed continuation

Date: 2026-10-14. Status: **IMPLEMENTED PROVIDER, REAL ACCEPTANCE OPEN**. The user approved
this written design after commit `6bb7b1b`. This extends the
approved native-sandbox design. No volumes, quotas, drivers or administrator
services have been created by this proposal.

## Intent and acceptance

Keep one ISyCode core and the existing Authority/Sentinel/approval/ledger owner.
Windows execution must not acquire an unsandboxed fallback. A real Windows
command must fail to write a file larger than the agreed 512 MiB ceiling,
including writes through alternative paths. A free-space check or a polling
monitor does not enforce that ceiling.

Current evidence: the 513 MiB control succeeds in ordinary NTFS scratch. This
session has no SeManageVolumePrivilege. No WinFsp/Dokan/ImDisk service or checked
driver path was found. An existing large drive is not bounded execution
storage. Its free capacity does not solve the acceptance failure.
Raw host observations are preserved in
`evidence/windows-bounded-storage-host-20261014.txt`; the driver/service probe
is limited to the named services and checked paths, not a census of every
possible filesystem provider.

## Options and recommendation

1. **Recommended: an explicitly provisioned, fixed-size VHD-backed NTFS volume,
   mounted before ISyCode runs.** A person prepares only this new virtual disk
   through an administrator session. The application consumes the mounted
   volume as an ordinary user, without a persistent elevated helper. The
   virtual filesystem's total capacity is no greater than 512 MiB. This is
   an aggregate ceiling, stricter than Linux's per-file ceiling; runtime and
   metadata reduce available workspace capacity. Volume provisioning and its
   identity/privacy checks must pass before this provider is usable.
2. A privileged per-run volume broker could allocate one disk per command,
   but adds an administrator service and an authorization surface. Defer it.
3. An explicitly selected Docker/Linux backend would be a separate feature
   and would not prove native Windows parity. It is not substituted here.

Neither host-wide NTFS quotas nor a directory-size monitor is selected.

## Provisioning boundary

The operator selects the new VHD backing-file location and a temporary mount
point. There are no built-in C:/D: paths or fixed drive-letter assumptions.
Provisioning creates a fresh fixed-size image; it never selects or formats an
existing physical disk or an existing user's volume. Attach/initialize/format
operations need their own exact identity checks and approval after review of
the implementation plan. Microsoft requires SeManageVolumePrivilege for
AttachVirtualDisk; the current session cannot demonstrate this stage.

The application does not elevate itself, install a driver, auto-mount a disk,
resize a volume or change host quotas. It refuses an absent or invalid provider.
Setup and unmount/removal require a human guide and recovery instructions.

## Runtime provider and configuration

Extend only the Windows adapter with a storage provider. Configuration supplies
the provisioned volume's persistent GUID and maximum capacity. Runtime probes
must verify actual volume identity, virtual backing, NTFS type, capacity,
current-user ownership and protected permissions. A marker, label, claimed
free-space number or drive letter is not sufficient evidence. API discovery
must not guess paths from installation directories.

Bind measured volume identity and capacity into the sandbox identity in the
approved request. Recheck before creating each owned scratch directory and
before process launch. Reject reparse/alias substitutions and unavailable
volumes. No automatic switch to an ordinary host directory is allowed.

Use the existing unique scratch ownership record and cleanup protocol inside
this dedicated volume. Runtime is read-only; workspace and temp are writable
only by the run's LPAC SID. The volume root and provisioning metadata remain
inaccessible for LPAC modification. Concurrent runs are isolated by their
profile SIDs but share the aggregate capacity; exhaustion fails preparation
or execution without changing the original workspace. Busy recovery remains
non-destructive and never unmounts storage belonging to another run.

## Close every writable route

The command must not be able to enlarge the VHD, write to its backing file or
access physical-volume/device handles. No such handles are inherited.

AppContainer's additional profile folder and registry storage must be
read-only for its SID before the command runs. Changing TEMP/LOCALAPPDATA alone
does not close these API-visible stores. File-folder protection has native
controls; registry protection and its failure-before-resume controls require
verification. A writable outside route blocks activation even if the virtual
volume itself is bounded.

## Required real controls

- Normal approved command, Unicode/space paths, receipt and measured promotion.
- A bounded 513 MiB write attempt fails inside the configured <=512 MiB volume;
  actual file size, process exit and remaining host space are recorded.
- Many smaller files, truncation, sparse writes and temp writes cannot exceed
  filesystem capacity or write through a second profile/device path.
- Host backing-file modification, volume-root/metadata modification and
  container profile folder/registry writes are denied.
- Invalid capacity, filesystem, substituted GUID, privacy or absent mount
  refuses before user code. Fault injection complements real volume controls.
- Owner death, cancellation, volume disappearance, exhaustion and concurrent
  runs leave original files untouched; cleanup only recovers owned scratch.
- Shared Linux owner regression remains green. Physical Linux terminal and
  full Windows product parity remain separate acceptance work.

The 513 MiB allocation control preserves at least 1 GiB free on the backing
host volume. No test fills a user's physical disk. This proposal does not enable
the current `NATIVE_ACCEPTED=False` guard.

## Sources and limits

- [Microsoft: AttachVirtualDisk](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-attachvirtualdisk)
- [Microsoft: About VHD, fixed and dynamic images](https://learn.microsoft.com/en-us/windows/win32/vstor/about-vhd)
- [Microsoft: GetAppContainerFolderPath](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-getappcontainerfolderpath)
- [Microsoft: GetAppContainerRegistryLocation](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-getappcontainerregistrylocation)

These describe mechanisms, not executed ISyCode volume acceptance. Provider
implementation, provisioning, identity verification and exhaustion controls
are all **NOT_DEMONSTRATED** until tested.
