# Capability inventory

Baseline source: `b80975517f8496b70b8f7c2d37f408cd839d6b27`, native Windows audit dated 2026-10-13.

| Capability | Current migration status | Acceptance still required |
| --- | --- | --- |
| Effect and operation ledger locks | Native adapters implemented | Continued crash/permission regression coverage |
| Iteration state and deletion | Native adapters implemented | File-symlink negative control on a privileged Windows test host |
| Chat sessions and recovery | Selected native flows verified | Live provider handoff and long-session dogfood |
| Authority policy and private action audit | Native ownership/DACL checks implemented; anonymous-token negative DACL witness passes | Access witness from a separately logged-on Windows identity; the five-user acceptance matrix is waived for this request |
| Workspace file recovery | Native preimages, stale-check and readback implemented | Same-user directory replacement risk remains documented |
| Git status/diff/approved commits | Native trusted installation discovery implemented | Wider Git installation layouts are not supported automatically |
| Native terminal startup | Windows startup tested in the earlier baseline audit; current headless flows tested | Physical mouse, fonts, clipboard and long interactive session |
| Command sandbox | Shared owner with POSIX adapter and native LPAC/Job prototype; private fixed-VHD provider and schema2 recovery; real VHD acceptance 13/13 PASS; lifecycle controls include TCP/UDP IPv4/IPv6, WinHTTP, host-to-LPAC named-pipe denial, abrupt-owner recovery, and a full lifecycle rerun (12 passed, 3 skipped); LPAC named-pipe creation was denied with ERROR_ACCESS_DENIED; exact-image remount and inspection passed after a real Windows reboot; Windows product activation remains disabled | Other IPC/device surfaces; AF_UNIX endpoint (host bind/connect unavailable, so NOT_DEMONSTRATED); reverse host access to a pipe created by LPAC (creation was denied); additional runtimes/project dependencies; separately logged-on identity ACL witness; standalone EXE install/update and power-loss recovery |
| Process cancellation outside these owners | Existing integrations have their own mechanisms | Native Windows child-tree termination and per-owner tests |
| Clipboard, LSP, MCP, RTK | Existing mechanisms, not globally certified by this migration | Individual native diagnostics, permissions and end-to-end evidence |
| Tailscale/mobile/private-access state | Additional POSIX-dependent code remains | Adapter inventory, privacy, process and live-service controls |
| Credentials/provider settings/observations | Existing keyring/metadata behavior retained | Remaining chmod/optional-lock stores need native privacy inventory |
| Distribution | Source PowerShell installer; wheel install/uninstall verified in a fresh private venv; one-file EXE smoke verified (`--version`, `--help`, `doctor`, `dirs`, `models`); updater Git environment has a Windows proxy/TLS allowlist | Clean dependency download; source installer uninstall; standalone EXE install/uninstall and supported upgrade; live proxied Git update query |
| Integrity-pinned bundled resources | Exact Git bytes restored; checkout conversion disabled | Continued clone/wheel catalog validation on both OS jobs |
| Hermetic regression suite | Linux full suite runs in CI; Windows full suite is gated in CI | Two hosted runs exposed Windows-only test/runtime assumptions. The latest correction adds private fixture roots, ignores the optional Python app-execution alias, fixes Windows launcher expectations, and tests fail-closed Git discovery. Local targeted selections pass; the full hosted rerun is pending. The five-user acceptance matrix is waived for this request |

No milestone or release gate is advanced by this inventory. A missing capability stays unavailable. Full parity requires functional, security and operational acceptance for every required workflow, not merely matching method names.

Current regression evidence (2026-10-15): the Windows UI/workspace selection
passes 39/39, the Windows parity failure selection passes 37 with 3 explicit
platform skips, and the Linux adapter selection passes 139 with 9 skips in a
non-root container. These selections overlap the broader suite. The fresh full
Windows non-integration run from D: passes 1827, with 323 skips, 11 integration
tests deselected, and 1 expected failure in 1838.80 seconds. The separate
Windows integration selection passes 5, skips 6 (five live Gateway tests and
the unavailable Bubblewrap control), and deselects 2151. The broker unit module
was also rerun after its Windows state-root fix: 5 passed, 3 integration tests
deselected. Across the complementary full-suite selections, 1832 pass, 329 skip,
and 1 expected failure. Raw output and hashes are recorded in the report and
`evidence/`. The command sandbox stays unavailable while `NATIVE_ACCEPTED=False`.

The updater regression selection on 2026-10-15 passes 36 tests with one
POSIX-only skip. Its clean one-file Windows EXE passes five non-mutating CLI
smokes from a disposable Unicode/spaces path. A real `update --check` could
not be demonstrated because this host has no configured proxy and direct
GitHub lookup fails; the frozen EXE also has no supported self-upgrade path.
See the final updater section in `REPORT.md` and
`evidence/windows-updater-proxy-20261015.txt`; captured test output is
`evidence/windows-updater-proxy-tests-r3-20261015.txt`.

The Windows native runtime allowlist selection passes 6/6. CPython is the only
accepted sandbox runtime; Node and Bun are present on this host but their names
and absolute executable paths are rejected. A pure wheel was built from a
private copy of the current source, installed into a fresh Unicode/spaces venv,
smoked with `--version` and `--help`, and uninstalled; the check used
`--no-deps` with system dependencies visible. The real-VHD lifecycle module
passes 12 with three explicit skips: two operator-controlled disappearance
controls were demonstrated separately, while the AF_UNIX host positive control
is unavailable. LPAC's named-pipe server creation is denied; host access to an
LPAC-created pipe is therefore untested. Details and hashes are in the latest
IPC/runtime section of `REPORT.md` and `evidence/`.

An anonymous Windows token was also used as a distinct-principal negative
control against the private metadata DACLs: `test_windows_private_identity.py`
passed without modifying the seeded files. The five-user acceptance matrix was
not run, as requested. That control is not equivalent to a separately logged-in
Windows account; the latter remains NOT_DEMONSTRATED. A full Windows 3.12
non-integration test job now gates package builds. The first two hosted runs
exposed ACL/runtime/UI/content-byte regressions and a test assumption about
trusted Git discovery. Additional local fixes now pass the native sandbox,
updater and hosted-regression selections. The latest full hosted rerun is
pending. See the final correction sections in `REPORT.md`; the five-user matrix
remains waived.
