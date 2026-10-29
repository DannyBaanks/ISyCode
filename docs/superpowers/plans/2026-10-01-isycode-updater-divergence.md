# `isycode actualizar` Divergence Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `isycode actualizar` safely integrate clean, non-conflicting local/remote divergence, and make the current checkout updateable without dropping any of its six local or four remote commits.

**Architecture:** Extend the existing self-updater to preflight divergence without touching the worktree, perform a merge commit when clean, and stop with exact conflicting paths otherwise. The sole deterministic exception is an isolated conflict in the generated authority-coverage snapshot: regenerate it from the merged live catalog rather than choosing either side's JSON by hand.

**Tech Stack:** Python 3.10+, existing `SelfUpdater`, Git argv subprocess calls, local temporary repositories, pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-isycode-updater-design.md` (the requested divergence behavior is an explicit extension to its original fast-forward-only behavior).

## Global Constraints

- Never use `pull`, reset, forced checkout, stash, clean, or rebase.
- Never integrate when tracked/untracked user changes exist.
- Keep both sides' commits; conflict-free divergence uses a merge commit, not history rewriting.
- Preflight conflicts before touching the worktree; abort and preserve `HEAD`, index, and files for all conflicts except the isolated canonical coverage snapshot, which is regenerated.
- Keep Git noninteractive, hooks disabled, system/global config disabled, and external helpers rejected.
- `--check` fetches and reports only; it never changes branch, index, files, environment, or launcher.
- Do not expose raw Git stderr, secrets, or credentials.

## Review Focus

- Clean divergence with independent changes: merge commit contains every local and remote commit.
- Divergence with code or add/add conflict: report exact paths and preserve `HEAD`, index, and worktree. The coverage snapshot exception must regenerate from merged source and abort on any other path or generator error.
- Dirty or ignored path collision: stop before merge and preserve the user's files.
- Merge preflight error, missing merge base, or Git version without supported tree output: fail closed with actionable guidance.
- Dependency sync failure after a completed merge: report code-updated/dependencies-unsynced distinctly and provide the exact venv retry command.

---

### Task 1: Divergence preflight and safe updater behavior

**Files:**
- Modify: `isycode/updater.py`
- Modify: `test_updater.py`
- Modify: `docs/superpowers/plans/2026-10-01-isycode-updater.md`

**Interfaces:**
- Keep `SelfUpdater.run(check_only=False) -> UpdateReport` and existing statuses; add an explicit conflict status only if CLI exit handling and report rendering distinguish it usefully.
- For `ahead > 0 and behind > 0`, use Git's non-mutating merge-tree preview. `--check` reports the mergeability and summary only. Normal update executes `git merge --no-edit FETCH_HEAD` only if preview is conflict-free; this creates a merge commit and preserves both histories.
- A conflicted or failed preflight does not run merge except for the exact generated snapshot case. That case uses `--no-commit`, regenerates through `authority_coverage_snapshot()`, stages only that report, commits both histories, and aborts if any check fails.

- [x] Add temporary local-repository tests for clean divergence, conflict, check-only divergence, dirty divergence, ignored-file collision, and preflight failure; assert both refs and relevant worktree bytes.
- [x] Run `python3 -m pytest -q test_updater.py`; 25 tests pass, including snapshot regeneration, check-only, and abort-on-generator-failure.
- [x] Implement non-mutating preflight and merge-only-on-clean behavior, retaining the existing fast-forward path when `ahead == 0`.
- [x] Verify divergence and existing updater cases; the focused updater tests passed.

### Task 2: Repair this checkout's generated snapshot conflict

**Files:**
- Modify: `docs/security/m15-authority-coverage.json` only as generated output
- Modify: `test_updater.py` only if a regression demonstrates a missing assertion

**Interfaces:**
- Use the merged code's `isycode.action_coverage.authority_coverage_snapshot()` as the source for `docs/security/m15-authority-coverage.json`, matching the assertion in `test_action_coverage.py`.
- Do not hand-select or discard the richer local report fields or upstream report fields.

- [x] Confirm the known divergence has no conflict outside `docs/security/m15-authority-coverage.json`; regenerate through the canonical snapshot function in the updater's isolated-merge path.
- [x] Test canonical regeneration, check-only preservation, and abort on generator error; run the snapshot assertion in the focused coverage batch.
- [ ] Verify local six commits and fetched four commits are all ancestors of the resulting branch; confirm `git status --short` contains no unrequested path changes.

### Task 3: Documentation, dependency sync, and end-to-end update report

**Files:**
- Modify: `README.md`
- Modify: `isycode/updater.py` only for a discovered reporting defect
- Modify: `test_updater.py` only for a discovered regression

- [x] Document clean divergence merge behavior, conflict stop behavior, and preservation of both histories.
- [x] Exercise check-only and normal divergence behavior against temporary local repositories in unit tests.
- [x] Run updater, action-coverage, and launcher-focused tests and `git diff --check`.

**Workspace limitation:** The real checkout remains `ahead 6 / behind 4` and has tracked edits plus user-owned untracked files. Running `isycode actualizar --check` fetched and listed the four incoming commits, then stopped before integration; `isycode-selftest/` and every other local file were preserved. No merge or ancestry claim is made for this checkout.
