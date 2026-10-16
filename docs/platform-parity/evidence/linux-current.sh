set -eu
apt-get update -qq
apt-get install -y -qq git bubblewrap libseccomp2 >/dev/null
git config --global --add safe.directory /repo
git config --global user.name ParityTest
git config --global user.email parity@test.invalid
git clone -q /repo /tmp/current
cd /tmp/current
cp -a /repo/src/. src/
cp -a /repo/tests/. tests/
cp /repo/pyproject.toml pyproject.toml
pip install -q -e '.[test]'
python -m pytest -q tests/test_platform_storage.py tests/test_iteration.py tests/test_effect_ledger.py tests/test_workspace_modes.py tests/test_action_audit.py tests/test_action_audit_segments.py tests/test_session_continuity_tui.py tests/test_tui_startup.py --maxfail=5
