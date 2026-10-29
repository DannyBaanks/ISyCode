# Native Windows verification — 2026-10-13

Source: DannyBaanks/ISyCode main, commit `b80975517f8496b70b8f7c2d37f408cd839d6b27`.
Checkout: `C:\Development\ISyCo Git\ISyCode`.
Host: Windows 11 Home, 10.0.26200, x64; Intel Xeon E5-2678 v3; Python 3.12.10; Textual 8.2.8.

## Scope and results

| Claim | Result | Evidence |
| --- | --- | --- |
| Fresh native installation | PASS, installed 1.0.0rc1 | install.log |
| Installed help/version/doctor | PASS | help.log, doctor.log; version printed ISyCode 1.0.0rc1 |
| Native console startup and onboarding | PASS for temporary Security workspace; three Esc presses reach prompt, Ctrl+C exits 0 | native-pty.json (partial tool transcript, some chunks truncated) |
| Basic Textual flows | PASS: 4 tests in 10.27s | tui-basic.log, tui-basic-exit.txt |
| Selected core tests | FAIL: 38 passed, 8 failed, 41 skipped; stopped at eight failures | core-flows.log, core-flows-exit.txt |
| Full hermetic suite | FAIL during collection: two modules import fcntl | suite.log, suite-exit.txt |
| Direct native VerifiedFS read/replace/readback | PASS; actual Windows final-handle-path API used | native-filesystem.log |
| Stale write negative control | PASS: refused and original bytes preserved | native-filesystem.log |
| Product effect ledger | DENIED: effect ledger lock unavailable | native-filesystem.log, core-flows.log |
| Live-provider end-to-end coding | NOT_DEMONSTRATED | No provider credentials supplied or live inference performed |

## Reproduced product blockers

1. `src/isycode/iteration.py:12` imports POSIX `fcntl` unconditionally. Both iteration test modules fail collection. The TUI session refresh also imports this module outside its exception handler (`tui_app_sessions.py:734`), causing an exception when sessions are enabled. The broader TUI flow run produced this traceback and was interrupted after it stopped making progress; it has no complete test summary.
2. `EffectLedger.exclusive()` requires `fcntl`; absence is deliberately fail-closed as `LedgerDenied: effect ledger lock is unavailable`. Classic edit flow fails here. Direct filesystem success does not demonstrate authorized product mutation.
3. Doctor reports command sandbox unavailable: Linux bubblewrap/libseccomp/Python are required. No unrestricted execution fallback was introduced.

Other selected test failures include Windows symlink privilege 1314, POSIX mode-bit expectations, and attempting to execute the POSIX install-path script (WinError 193). These are separate from demonstrated product blockers.

## Exact test commands

Run from the checkout using PowerShell, with `PYTHONUTF8=1`.

```powershell
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[test]'
& .\.venv\Scripts\isycode.exe --version
& .\.venv\Scripts\isycode.exe --help
& .\.venv\Scripts\isycode.exe doctor --json
& .\.venv\Scripts\python.exe -m pytest -q -m 'not integration'
& .\.venv\Scripts\python.exe -m pytest -vv tests/test_workspace_root.py tests/test_workspace_authority.py tests/test_workspace_modes.py tests/test_workspace_write.py tests/test_security_contract.py tests/test_launcher.py --maxfail=8
& .\.venv\Scripts\python.exe -m pytest -vv tests/test_tui_startup.py tests/test_workspace_write_tui.py -o faulthandler_timeout=30
```

The initial broader TUI command selected `test_tui_startup.py`, `test_daily_tui.py`, `test_session_continuity_tui.py`, and `test_workspace_write_tui.py` with `-q`. It was interrupted with Ctrl+C (process exit 1) after the fcntl traceback. A second full-suite command with `--continue-on-collection-errors` was also interrupted (exit 1); its empty buffered log is not a result. Neither interrupted run certifies the remainder of the suite.

Native startup used checkout-local, gitignored `ISYCODE_STATE_HOME`, `XDG_CONFIG_HOME`, and `XDG_STATE_HOME` under `.isycode/`. No source changes, pushes, external integration calls, Bridge daemon, global terminal preferences, or sandbox bypasses were made.

## NOT_DEMONSTRATED

Complete Windows compatibility, persistent session workflows, authorized writes through the product, sandboxed commands, live model conversation, live MCP/Gateway, physical clipboard roundtrip, packaged EXE, and full-suite execution. This audit tests the existing source; it does not port the POSIX lock/security implementations to Windows.
