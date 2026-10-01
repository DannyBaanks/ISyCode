# `isycode actualizar` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `isycode actualizar` and `isycode actualizar --check` to safely fast-forward a clean ISyCode checkout or prepare an isolated user installation from the official repository.

**Architecture:** Keep update logic in `isycode/updater.py`, with an injectable command runner and explicit report statuses so Git behavior can be tested against temporary local repositories. Dispatch the Spanish command before TUI startup; bootstrap a user-owned source checkout and `.venv` only when the running package has no Git checkout, and only link the launcher when it is absent or is a verified ISyCode-generated entry point.

**Tech Stack:** Python 3.10+, `subprocess` argv lists, Git, `venv`, pip, pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-isycode-updater-design.md`

## Global Constraints

- Never use `pull`, reset, forced checkout, stash, clean, or rebase.
- Never alter a dirty checkout; include tracked and untracked files in the dirty check and show incoming commit/diff information.
- Only accept the canonical ISyCode GitHub repository or a GitHub repository whose basename is `ISyCode`; never rewrite an existing remote.
- Invoke Git and Python with argument arrays, fixed working directories, noninteractive settings, system/global Git config disabled, hooks disabled, and no external diff/textconv.
- Reject repository-local configured filters or other executable Git helpers before fetching or checkout.
- `--check` may fetch into Git metadata but must not alter the branch, checkout files, launcher, or virtual environment.
- User installation lives under `$XDG_DATA_HOME/isycode/source` or `~/.local/share/isycode/source`; never write into the invocation directory.
- Never replace a command unless it is absent, already a symlink to this managed source launcher, or an exact, bounded, user-owned pip-generated `isycode` entry point.
- Never use privileges, print credentials, expose raw Git stderr, or create user commits/pushes.

## Review Focus

- Current branch has no upstream or remote ref is malformed: stop with exact `git branch --set-upstream-to` guidance.
- Dirty tracked and untracked paths: preserve both; show escaped status and incoming summary; no merge/pip/launcher changes.
- Remote has credentials, wrong host, wrong repository name, or remote-local filters: reject before fetch/checkout.
- Remote is behind, diverged, or fetch fails: update only by fast-forward; preserve `HEAD` and working tree on all denials.
- User data directory or command already exists but is not an ISyCode-owned path: preserve it and print the prepared launcher's exact path.

---

### Task 1: Safe checkout inspection and fast-forward

**Files:**
- Create: `isycode/updater.py`
- Test: `test_updater.py`

**Interfaces:**
- Produces `UpdateReport(status: str, lines: tuple[str, ...])` and `SelfUpdater(...).run(check_only: bool = False) -> UpdateReport`.
- `status` is one of `updated`, `available`, `current`, `dirty`, `blocked`, or `error`; callers render its Spanish lines without exposing raw subprocess output.
- Uses an injectable command runner and source root; production defaults to `subprocess.run` and the package's containing checkout.

- [x] Write tests using temporary bare/local Git repositories for clean fast-forward, check-only, dirty tracked/untracked paths, divergence, wrong remote, embedded remote credentials, fetch failure, unsafe Git config, and ignored-file collisions.
- [x] Confirm the initial tests fail because updater behavior is missing.
- [x] Implement checkout discovery, Git environment/argv policy, remote and filter validation, upstream fetch, incoming summary, clean-tree gate, and `merge --ff-only`.
- [x] Verify `--check` leaves `HEAD`, index, working files, and environment untouched while reporting incoming commits and a safe diff-review command.
- [x] Run focused updater tests and inspect report/status behavior.

### Task 2: User bootstrap, virtualenv, and launcher ownership

**Files:**
- Modify: `isycode/updater.py`
- Modify: `test_updater.py`
- Modify: `test_launcher.py`

**Interfaces:**
- User data root follows `XDG_DATA_HOME` when absolute, otherwise `~/.local/share`; its managed checkout is `isycode/source` and its environment is `isycode/source/.venv`.
- Official bootstrap URL is `https://github.com/DannyBaanks/ISyCode.git`.
- `--check` performs remote discovery only for a missing checkout; normal execution may clone, create `.venv`, install `-e .`, then manage the command.

- [x] Write tests for missing checkout check-only, local bare remote bootstrap, invalid existing destination, pip environment setup, pip entry-point recognition, and foreign launcher collision.
- [x] Implement staged bootstrap, `.venv` creation/sync without deleting an existing environment, bounded pip-script recognition, managed launcher linking, and a preserved-path instruction for foreign collisions.
- [x] Run focused tests and assert existing destination and launcher contents remain intact on failure/collision.

### Task 3: CLI command, help, and user guide

**Files:**
- Modify: `isycode/launcher.py`
- Modify: `test_launcher.py`
- Modify: `README.md`

**Interfaces:**
- `isycode actualizar` invokes `SelfUpdater.run(check_only=False)`.
- `isycode actualizar --check` invokes `SelfUpdater.run(check_only=True)`.
- Invalid updater arguments return exit code 2; update errors return a nonzero exit code; successful update/current/prepared outcomes return 0.
- Output and help are in Spanish.

- [x] Write dispatcher tests for both modes, bad flags, and Spanish help.
- [x] Add dispatch before normal TUI routing and document behavior, local-change protection, `--check`, source installs, and foreign launcher collisions.
- [x] Run launcher tests and verify `isycode --help` lists both update forms.

### Task 4: Full regression and completion record

**Files:**
- Modify: `test_updater.py` or focused docs only if a discovered gap requires it.

- [ ] Run the project hermetic suite `python3 -m pytest -q -m "not integration"` using the repository's supported Textual/Rich environment. (Ran: 935 passed, 2 unrelated pre-existing failures, 1 skipped, 11 deselected.)
- [x] Run `git diff --check`, `isycode --help`, and temporary-repository end-to-end checks for check-only, fast-forward, bootstrap, and dirty-tree stop.
- [x] Confirm no tests contact GitHub, no real credentials are used, and no user untracked file was changed.
- [x] Record test results, the two conservative rulings, and platform scope in the SDD ledger.
