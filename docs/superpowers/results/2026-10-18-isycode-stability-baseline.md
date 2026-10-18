# ISyCode TUI stability baseline — 2026-10-18

## Scope and environment

This baseline covers the previously reported native ChatGPT login/cancel test and interrupted-turn resume test. No production files were changed during the baseline runs. The checked-out source at baseline was commit `1b7a3ed4a28dc576d3bbaa4d2603e9cd40c54eff` on `codex/gmail-hive`.

- Host: Linux `DannyISyCo 7.0.0-38-generic`, Ubuntu 24.04 x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Textual: 8.2.8
- Captured: `2026-10-18T01:44:56-06:00`

## Focused baseline

Exact command:

```bash
python -m pytest -q tests/test_chatgpt_auth_tui.py::test_native_subscription_login_and_cancel_never_save_challenge tests/test_ux_polish_and_resume.py::test_area_f_interrupted_turn_capture_and_resume
```

Result: exit 0, **3 passed in 4.90s**. This Linux pass does not clear the historical Windows failure.

Raw captured output: `.superpowers/sdd/2026-10-18-isycode-tui-stability/task-1-focused.log`

SHA-256: `6be18f71891a89285d6fb0b850dc02e3754e549d742fb9f46332665e87702c9f`

## Resume stress

The exact resume test was run 20 separate times with `python -m pytest -q`. **20/20 passed**; no failing iteration or traceback was observed. The complete per-iteration output is in `.superpowers/sdd/2026-10-18-isycode-tui-stability/task-1-resume-stress.log`.

SHA-256: `bdabfeb31c687754aa69f74ef7cbb36c908ad916a82b9e7eb75b56f1bb928691`

## Historical CI observation

Run [38974723145](https://github.com/DannyBaanks/ISyCode/actions/runs/38974723145) concluded `failure`. The Windows job [Tests (Windows)](https://github.com/DannyBaanks/ISyCode/actions/runs/38974723145/job/117221278935) failed; Linux, Linux/Textual 8, and gate-evidence jobs succeeded. The failure was previously described as a `PermissionError` while reading test state. GitHub's `gh run view --job 117221278935 --log` and `--log-failed` returned no log lines in this environment, so the exact stack trace and cause are **NOT_DEMONSTRATED** here. The failure was not reproduced locally because this host is Linux; a Windows runner is still required.

## Reproduction status

- Native login/cancel test: passes on this Linux host; Windows historical failure remains unverified.
- Interrupted-turn resume: passes locally and in 20/20 repetitions.
- Journal worker race as a cause of the Windows failure: **NOT_DEMONSTRATED**. No lifecycle fix is justified by this baseline alone.
- Later multi-turn rendering regression: tracked and tested separately in the approved plan; it is not inferred from the historical Windows job.

## Post-fix verification (2026-10-18, follow-up session)

Follow-up verification on the same host and branch (`codex/gmail-hive`), after the Task 3–7 fixes were applied:

- Focused chat/streaming: `python3 -m pytest -q tests/test_chat_sequence.py tests/test_ux_polish_and_resume.py::test_area_f_interrupted_turn_capture_and_resume` → **15 passed in 16.72 s**.
- Focused auth/model/folders: `python3 -m pytest -q tests/test_model_button.py tests/test_model_decision_surface.py tests/test_chatgpt_auth_tui.py tests/test_provider_auth_methods.py tests/test_workspace_folders.py tests/test_workspace_folders_tui.py` → **66 passed in 50.57 s**.
- Task 7 profile: targeted Markdown render CPU reduced by at least 97% against the pre-change baseline (see `2026-10-18-isycode-stream-profile.md`).
- Full local suite `python3 -m pytest -q -m "not integration"`:
  - Plain run: 2044 passed, 151 skipped, 11 deselected; 2 failures in subprocess-import tests (`test_native_cli_stdio`, `test_provider_metadata_native`) caused by running without an editable install — both pass immediately with `PYTHONPATH=src`, which matches CI's `pip install -e '.[test]'`.
  - Re-run with `PYTHONPATH=src`: **2045 passed**, 151 skipped, 11 deselected, 1 failure: `tests/test_file_preview_tui.py::test_copy_path_for_selected_directory`. That test passes standalone (2.00 s) and as a whole file (2 passed, 3.66 s); it failed only under a loaded full-suite run and is recorded as a timing flake, not a regression of this change (cause `NOT_DEMONSTRATED`).
  - Log: `.superpowers/sdd/2026-10-18-isycode-tui-stability/task-8-full-suite-pythonpath.log`, sha256 `e1781961e1c46036e8f6ddff02ed9b1a73ee45edf77b709604bd383ea05666fb`.
- Platform CI on PR [#53](https://github.com/DannyBaanks/ISyCode/pull/53) (head `3d5fed5`), `pull_request` run [39114476126](https://github.com/DannyBaanks/ISyCode/actions/runs/39114476126): **Tests (Linux)** passed ([job 117637334718](https://github.com/DannyBaanks/ISyCode/actions/runs/39114476126/job/117637334718)), **Tests (Linux, Textual 8)** passed ([job 117637334893](https://github.com/DannyBaanks/ISyCode/actions/runs/39114476126/job/117637334893)), **Gate evidence** passed ([job 117637334999](https://github.com/DannyBaanks/ISyCode/actions/runs/39114476126/job/117637334999)), **Tests (Windows)** passed with `1857 passed, 339 skipped, 11 deselected, 1 xfailed in 1111.56s` ([job 117637335051](https://github.com/DannyBaanks/ISyCode/actions/runs/39114476126/job/117637335051)); package jobs linux-x86_64, windows-x86_64 and macos-arm64 passed; the draft release job is skipped by design on a branch.
- Parallel `push` run [39114441006](https://github.com/DannyBaanks/ISyCode/actions/runs/39114441006) passed the same jobs, and the native platform contracts workflow run [39114475979](https://github.com/DannyBaanks/ISyCode/actions/runs/39114475979) passed on `ubuntu-latest` and `windows-latest`.
- `tests/test_chatgpt_auth_tui.py` and `tests/test_ux_polish_and_resume.py` carry no platform skip guards, so their parametrized cases ran inside the green Windows suite; the historical failure's cause remains `NOT_DEMONSTRATED`, but the current head passes Windows.
- Flake observations on head `688d826` (docs-only change; every comparison below is within the same commit):
  - `pull_request` run [39116023304](https://github.com/DannyBaanks/ISyCode/actions/runs/39116023304) failed once on **Tests (Linux, Textual 8)** with `textual.pilot.WaitForScreenTimeout` in `tests/test_ux_polish_and_resume.py::test_area_f_interrupted_turn_capture_and_resume`; the parallel `push` run [39116020134](https://github.com/DannyBaanks/ISyCode/actions/runs/39116020134) passed the same job, and the failed job's rerun also passed. This matches Task 1's intermittent observation; the cause stays `NOT_DEMONSTRATED`.
  - `push` run 39116020134 (**Tests (Windows)**): the suite reported `1 failed, 1766 passed, 294 skipped, 11 deselected, 1 xfailed in 3562.27s` with `tests/test_visual_tui.py::test_long_workspace_header_keeps_status_and_path_end` ("workspace banner did not fit after sidebar layout", 10 s deadline) on a runner that took 59:22 for the suite; the job then hit its 60-minute timeout and GitHub marked it cancelled. The same commit's `pull_request` Windows job passed the full suite in 18:31 (`1857 passed`). Local log: `task-8-windows-timeout-job.log`, sha256 `2e380bf16d6e717c71c82e7f95d6be419649bbdc968836ac5e1131a3baff99f5`.
  - Both are load/timing flakes on slow or unlucky runners; neither reproduces in the parallel green job on the same commit, and no product change is justified by them.

## Release recommendation

Ship after human review and merge: local evidence plus PR #53 platform CI (Linux 3.10, Linux/Textual 8, Windows, gate evidence, and packages) are green on head `3d5fed5`. The historical Windows failure keeps its cause `NOT_DEMONSTRATED`, but it does not fail the current head. This evidence commit re-runs CI; its result is visible in the PR checks. Gmail Hive remains deferred and is not part of this delivery.
