set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git bubblewrap libseccomp2 >/dev/null
git config --global --add safe.directory /repo
git clone -q /repo /tmp/current
cd /tmp/current
cp -a /repo/src/. src/
cp -a /repo/tests/. tests/
cp /repo/pyproject.toml pyproject.toml
cp /repo/docs/security/m15-authority-coverage.json docs/security/m15-authority-coverage.json
pip install -q -e '.[test]'
useradd --create-home parity
chown -R parity:parity /tmp/current
if [ "${PARITY_FOCUS:-}" = all ]; then
    su parity -s /bin/sh -c 'cd /tmp/current; git config --global user.name ParityTest; git config --global user.email parity@test.invalid; python -m pytest -q -m "not integration" --maxfail=5'
elif [ "${PARITY_FOCUS:-}" = storage ]; then
    su parity -s /bin/sh -c 'cd /tmp/current; git config --global user.name ParityTest; git config --global user.email parity@test.invalid; python -m pytest -q tests/test_platform_storage.py tests/test_iteration.py tests/test_effect_ledger.py tests/test_workspace_modes.py tests/test_action_audit.py tests/test_action_audit_segments.py tests/test_git_owner.py tests/test_native_toolkit.py::test_bundled_skill_catalog_is_pinned_and_validated tests/test_native_toolkit.py::test_native_skill_activation_enters_owned_prompt_without_granting_tools tests/test_session_continuity_guard.py::test_old_sessions_stay_readable_and_the_format_is_unchanged --maxfail=5'
else
    su parity -s /bin/sh -c 'cd /tmp/current; git config --global user.name ParityTest; git config --global user.email parity@test.invalid; python -m pytest -q tests/test_platform_storage.py tests/test_iteration.py tests/test_effect_ledger.py tests/test_workspace_modes.py tests/test_action_audit.py tests/test_action_audit_segments.py tests/test_session_continuity_tui.py tests/test_tui_startup.py tests/test_git_owner.py tests/test_daily_tui.py -m "not integration" --maxfail=5'
fi
