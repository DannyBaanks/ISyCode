# RTK native local validation — 2026-10-09

Scope: optional native RTK output compression and its TUI controls. No Classic/Security milestone is promoted by this report. No external model or provider was used.

Environment: Ubuntu Linux, Python from the original ISyCode venv, real RTK 0.51.0 at /usr/local/bin/rtk and real bubblewrap. RTK SHA-256: b947215511bfd8f5f6eb12c6b6d4a9f70b72e9ce37442cfa4df2352b033cd0ea.

The headless TUI fixture uses synthetic workspace data and simulated user approval. It opened /rtk through the real router, enabled the inspected binary, approved the original grep command once, and recalled the original output by verified hash. Captured output: 7282 bytes; model output: 222 bytes; saved: 7060 bytes. See the unchanged probe source, output, result and SVG.

Native regression and focused menu/model/import controls are preserved in the accompanying logs. Full-suite verification is recorded separately when complete. The probe is NOT evidence of real-provider behavior or human gate completion. Savings are byte-based estimates, not provider billing.

Negative controls cover unsupported rewrites, malformed suggestions, changed binaries, private-file symlinks/hardlinks/FIFOs, filter failures, original nonzero exits, and failure to archive raw output before file promotion. Original command arguments, Authority/Sentinel decisions, network isolation and approvals remain the execution boundary.

Exact local commands:

```bash
TMPDIR=/run/user/1000 '/home/danny/Development/ISyCo Git/ISyCode/.venv/bin/python' -m pytest -q tests/test_rtk_integration.py tests/test_rtk_ui.py
TMPDIR=/run/user/1000 '/home/danny/Development/ISyCo Git/ISyCode/.venv/bin/python' -m pytest -q tests/test_menu_kinds.py tests/test_model_reasoning_ui.py::test_model_accordions_filter_and_open_provider_reasoning tests/test_optional_isymotron.py::test_tui_module_import_does_not_require_isymotron_checkout
```

Earlier broad runs were interrupted or used an incorrect base interpreter; their logs remain in /tmp/isycode-rtk-native-evidence-20261009. They are not reported as passes. One broad run exposed the missing Preferences category for RTK; the focused control above verifies its repair.

NOT_DEMONSTRATED: parity with every RTK wrapper, complete tool/model coverage, real-provider canary, human usability acceptance, soak stability.

Additional execution-boundary checks: 3 passed (authority-rtk-final.log). An RTK allow decision with an approval still cannot replace a missing workspace grant; RTK ask requires explicit approval in Classic; replacing the binary after approval denies before starting the command.

```bash
TMPDIR=/run/user/1000 '/home/danny/Development/ISyCo Git/ISyCode/.venv/bin/python' -m pytest -q tests/test_rtk_authority.py
```

Preview launcher installed separately at ~/.local/bin/isycode-rtk; --help succeeded. It uses the isolated /tmp checkout and the original venv. The normal isycode launcher and original dirty checkout were preserved. This preview is temporary and depends on that checkout remaining present.

## Completed full-suite control

Full run exit status: 0. Result: **1700 passed, 8 skipped in 613.50s**. Unchanged raw log: full-suite-final3.log. The suite collected before the three additional RTK authority tests were added; those passed separately. This run verifies the RTK source at 4614b41 on base 2a8e696, before later main merges. No product-source changes were made during the run. Additional combined controls (rtk-final-controls-v2.log) passed: 45 tests.

```bash
TMPDIR=/run/user/1000 '/home/danny/Development/ISyCo Git/ISyCode/.venv/bin/python' -m pytest -q --basetemp=/run/user/1000/isycode-rtk-pytest-20261009-final3
```

During verification, main advanced to 43aab28 (native memory and model selector). Both lower stack branches were merged with main without rewriting published history, the authority snapshot was regenerated from its executable generator, and the UI branch merged the evidence branch. The earlier full-suite result is not claimed for these new main changes; post-merge controls and CI are recorded separately.

Post-main controls completed with exit 0: **72 passed in 53.70s**, unchanged log post-main-controls.log. Coverage: RTK/native UI/authority, executable authority snapshot, native memory, model selection, menu categories/reasoning and optional IsyMotron imports.

```bash
TMPDIR=/run/user/1000 '/home/danny/Development/ISyCo Git/ISyCode/.venv/bin/python' -m pytest -q tests/test_rtk_integration.py tests/test_rtk_ui.py tests/test_rtk_authority.py tests/test_action_coverage.py tests/test_workspace_memory.py tests/test_model_decision_surface.py tests/test_menu_kinds.py tests/test_model_reasoning_ui.py tests/test_optional_isymotron.py
```
