set -eu
apt-get update -qq
apt-get install -y -qq git >/dev/null
git config --global --add safe.directory /repo
git clone -q /repo /tmp/baseline
cd /tmp/baseline
pip install -q -e '.[test]'
git config --global user.name ParityTest
git config --global user.email parity@test.invalid
python -m pytest -q tests/test_iteration.py tests/test_workspace_modes.py tests/test_session_continuity_tui.py tests/test_tui_startup.py
