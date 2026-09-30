# Task 2 report: private Tailscale ownership state

## Outcome

Implemented `isycode/private_access.py` and `test_private_access.py`.
`PrivateAccessStateStore` persists a strictly allowlisted, per-user state record
under the existing ISyCode XDG state root. The separate `OwnedServeRoute`
type captures a route ID, tailnet host/path, exact loopback target, creation
time, and last verified status. The module documentation explicitly says this
record is only an ownership hint: removal must independently match fresh
`tailscale serve get-config --all` output.

The JSON envelope accepts only the owner marker, state version, adapter
version, and route list. Route objects accept only the six identity/status
fields. Unknown fields (including credential/auth/command-output fields),
wrong owner/version, malformed structures, oversized input, symlinks,
non-regular files, hard links, and unsafe POSIX ownership/permissions fail
closed. Missing files load as an empty state. Writes use an exclusive
no-follow temporary regular file, `fsync`, and atomic replacement; POSIX
parent/file modes are `0700`/`0600`.

## TDD evidence

- Before implementation, `pytest -q test_private_access.py` failed during
  collection because `isycode.private_access` did not exist.
- After implementation, `pytest -q test_private_access.py`: **10 passed**.
- Cases cover missing-file recovery and record/clear, atomic create/replace,
  POSIX permissions, symlink rejection, malformed/oversized JSON, wrong owner,
  wrong version, and rejection of an unexpected auth URL field.
- `git diff --check`: passed.

## Scope and review

Only Task 2 implementation, its focused tests, and this report are included in
the commit. The working tree already had a modified
`docs/superpowers/plans/2026-09-29-private-tailnet-setup.md` at task start; it
was left untouched and excluded. No Tailscale route mutation or live-route
ownership inference was added.

## Limitations

This task adds storage only. Task 6 must supply the fresh live configuration
and route-status comparisons before any route removal; this store does not
claim that a saved record proves ownership.

## Review follow-up: bounded writes and directory traversal

Addressed review findings in a follow-up commit. The store now checks every
existing path component for symlinks before creating or resolving the state
directory. Writes validate the route count and exact route values, serialize
before replacement, and reject payloads above `MAX_BYTES`; therefore each
successful write satisfies the same count and byte bounds enforced on load.

Additional regression tests verify the eight-route boundary, rejection of a
ninth route without changing the previous file, encoded-size rejection before
replacement, preservation of existing state when atomic replacement fails,
symlinked-parent rejection, and wrong adapter-version rejection.

TDD evidence: before the fix, the new route-count and symlinked-parent tests
failed (**2 failed, 13 passed**). After the fix, `pytest -q test_private_access.py` reported **15 passed** and `git diff --check` passed.

## Review follow-up 2: race-resistant state directory access

Replaced component `lstat` followed by path-based creation with a POSIX walk
that opens each directory relative to its already-pinned parent descriptor,
using `O_DIRECTORY | O_NOFOLLOW`. Missing components are created with
`mkdirat` semantics through `dir_fd`, then opened the same way. File inspection,
temporary-file creation, atomic replacement, permission setting, and cleanup
are all anchored to the retained state-directory descriptor, so later pathname
swaps cannot redirect those operations. The non-POSIX fallback retains the
platform's path checks.

A deterministic regression test injects an ancestor rename and symlink swap
after that ancestor descriptor is opened but before the child is created. The
old path-based implementation failed by creating under the attacker-selected
target. With descriptor-anchored operations, no state directory appears at
that target and the store can read back its record via the pinned descriptor.

TDD evidence: the race test failed before the change because the swapped target
received the state directory. After the change, `pytest -q test_private_access.py` reported **16 passed** and `git diff --check` passed.
