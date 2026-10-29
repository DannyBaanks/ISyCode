# Profile-storage review — 2026-10-14

Independent reviewer: `/root/profile_storage_review`, read-only, fresh context;
baseline `673be80`. The reviewer did not run tests during the concurrent native
verification and reported no actionable correctness regression.

The review examined actual child token SID binding, caller restoration, owned
profile-folder/API discovery, protected recursive registry DACL, guard ordering
before ResumeThread and the continued `NATIVE_ACCEPTED=False` state.

Requested additional acceptance: wrong SID, existing impersonation refusal,
discovery/ACL failure with no resume and restored caller, preservation of another
owned seeded profile's ACLs, subkey-creation and DACL-rights denial. These are
implemented in `tests/test_windows_sandbox_registry.py`. The first run had five
passes and a test-harness AttributeError: this pywin32 descriptor does not expose
GetSecurityDescriptorBinaryForm. The witness now compares owner/DACL SDDL using
the supported conversion API; the failed output is retained separately.

Final follow-up found a P2 witness gap: the target was already prepared when
the sibling folder ACL snapshot was taken, so it only witnessed launcher-time
registry work. The revised test creates and snapshots the sibling first, then
prepares and launches the target, comparing the sibling folder ACL after both.

The reviewer agreed that namespace refusal has no downside for current factory
callers and recommended it before registry mutation. Generation, recovery and
registry guard now share the same profile-prefix validation. The namespace is
only a scope restriction: token SID, discovered moniker and registry-owner
checks are retained; a matching name alone is not proof of fresh ownership.
The final read-only source inspection found no blocking defect in that delta.

This review is scoped, not comprehensive containment certification. The
proposed fixed-VHD provider is not implemented; write-budget acceptance remains
failed and native product activation remains blocked.
