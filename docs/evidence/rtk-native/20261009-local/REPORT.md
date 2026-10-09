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
