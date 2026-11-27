# ISyCode IDE (Desktop Qt6)

Native desktop IDE for ISyCode built with **Python >=3.11 + PySide6 (Qt6)**, featuring PLAN/CODER modes, explicit host approval cards, verifiable receipts, multi-file editor tabs, integrated host shell, GitHub repository sync, and ISyCo / ISyMCP ecosystem integration.

## Provenance

- **Origin:** Local desktop IDE codebase (`/home/danny/Development/ISyCode-IDE`, v`0.4.0`), originally created on an `IsyVM` worktree (`core/`, `bridge/`, `engine/`, `isyvm/`, `sandbox/`, `verifier/`, `ui/`).
- **History note:** No common Git history with `src/isycode/` (`main @ a189c0b`); imported as `ide/` on `ide/catchup` with all catch-up fixes (Fases 1–3) applied and verified.
- **Note on core divergence:** `ide/` currently runs on its self-contained `core/` runtime while `src/isycode/` holds the newer TUI/CLI core (369 commits ahead since `2026-10-11`, including PR #128 A1–A8 hardening). Converging `ide/` onto `src/isycode/` is tracked as a separate architectural decision.

## Quick Start

```bash
cd ide
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,ui]"
.venv/bin/python -P -m ui.main /path/to/your/project
```

> Use `-P` (Python 3.11+ safe path) so the current working directory cannot shadow `ide/core/` if launched from a repository that also has a `core/` package.

## Running Tests

```bash
cd ide
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q
```

## Integrations

- **ISyCo & ISyMCP tab** (`Herramientas → ISyCo & ISyMCP`): detects and monitors ISyMCP Hub (`:8798` / `:8799`, `~/.config/isycode/mcp.json`), `isymem`, `ziggrep`, `isycode`, `isyco`, and `gh` CLI.
- **GitHub panel:** authenticated via `gh` CLI (`DannyBaanks`), with public ISyCo repo filter, linked local checkouts, dated remote/local sync checks, and reviewed fast-forward pull.
- **Security model:** strict workspace containment (`PATH_OUTSIDE_WORKSPACE` guard with actionable guidance), `LINUX_ISOLATED` offline tmpfs execution for commands, and OS keyring detection (never falls back to plaintext files).
