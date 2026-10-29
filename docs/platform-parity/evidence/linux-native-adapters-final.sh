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
su parity -s /bin/sh -c 'cd /tmp/current; git config --global user.name ParityTest; git config --global user.email parity@test.invalid; python -m pytest -q tests/test_command_runner.py tests/test_command_responsiveness.py tests/test_platform_sandbox.py tests/test_workspace_modes.py tests/test_effect_ledger.py tests/test_staging.py tests/test_diagnostics.py tests/test_credential_vault_native.py tests/test_credentials_keyring_failure.py tests/test_credential_owner.py tests/test_clipboard_owner.py tests/test_image_attachments.py tests/test_capability_observations.py tests/test_provider_metadata_native.py tests/test_daily_provider_regressions.py tests/test_provider_catalog.py tests/test_model_availability.py tests/test_audit_shadow_import_redaction.py tests/test_action_coverage.py::test_checked_in_snapshot_matches_live_catalog_and_owners -m "not integration" --maxfail=3'
