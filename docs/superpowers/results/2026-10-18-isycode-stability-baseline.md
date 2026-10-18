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
