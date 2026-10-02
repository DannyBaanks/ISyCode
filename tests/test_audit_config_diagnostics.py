"""Audit regressions for provider credential isolation and local diagnostics."""
import json
import os

import pytest

from isycode.config import load_api_key
from isycode.diagnostics import collect_diagnostics, format_diagnostics
from isycode.launcher import main
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture
def isolated_keys(monkeypatch, tmp_path):
    for name in (
        'ISYCODE_PROVIDER', 'ISYMOTRON_PROVIDER', 'ISYMOTRON_API_KEY',
        'ISYMOTRON_API_KEY_FILE', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY',
        'NVIDIA_NIM_API_KEY', 'NEBIUS_API_KEY', 'GROQ_API_KEY',
        'OPENROUTER_API_KEY', 'OLLAMA_API_KEY', 'LLAMACPP_API_KEY',
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('ISYMOTRON_KEY_STORE', str(tmp_path / 'keys.env'))
    return tmp_path


@pytest.mark.parametrize('override', ['environment', 'file'])
@pytest.mark.parametrize('active_variable', ['ISYCODE_PROVIDER', 'ISYMOTRON_PROVIDER'])
def test_explicit_other_provider_never_uses_active_generic_key(
        isolated_keys, monkeypatch, override, active_variable):
    monkeypatch.setenv(active_variable, 'nvidia')
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-openai-key')
    if override == 'environment':
        monkeypatch.setenv('ISYMOTRON_API_KEY', 'fixture-active-key')
    else:
        key_file = isolated_keys / 'active-key.txt'
        key_file.write_text('fixture-active-key', encoding='utf-8')
        monkeypatch.setenv('ISYMOTRON_API_KEY_FILE', str(key_file))
    assert load_api_key('OPENAI') == 'fixture-openai-key'


@pytest.mark.parametrize('source', ['environment', 'store'])
def test_anthropic_key_resolves_from_its_own_source(isolated_keys, monkeypatch, source):
    monkeypatch.setenv('ISYCODE_PROVIDER', 'nvidia')
    monkeypatch.setenv('ISYMOTRON_API_KEY', 'fixture-active-key')
    if source == 'environment':
        monkeypatch.setenv('ANTHROPIC_API_KEY', ' fixture-anthropic-key ')
    else:
        (isolated_keys / 'keys.env').write_text(
            'NVIDIA_NIM_API_KEY=fixture-active-key\n'
            'ANTHROPIC_API_KEY=fixture-anthropic-key\n', encoding='utf-8')
    assert load_api_key('anthropic') == 'fixture-anthropic-key'


@pytest.mark.parametrize('requested', [None, 'NVIDIA'])
@pytest.mark.parametrize('override', ['environment', 'file'])
def test_active_provider_keeps_generic_override_precedence(
        isolated_keys, monkeypatch, requested, override):
    monkeypatch.setenv('ISYCODE_PROVIDER', 'nvidia')
    monkeypatch.setenv('ISYMOTRON_PROVIDER', 'openai')
    monkeypatch.setenv('NVIDIA_NIM_API_KEY', 'fixture-provider-key')
    if override == 'environment':
        monkeypatch.setenv('ISYMOTRON_API_KEY', ' fixture-active-key ')
    else:
        key_file = isolated_keys / 'active-key.txt'
        key_file.write_text(' fixture-active-key ', encoding='utf-8')
        monkeypatch.setenv('ISYMOTRON_API_KEY_FILE', str(key_file))
    assert load_api_key(requested) == 'fixture-active-key'


@pytest.mark.parametrize('override', ['environment', 'missing-file'])
def test_missing_other_provider_key_does_not_fall_back_to_generic(
        isolated_keys, monkeypatch, override):
    monkeypatch.setenv('ISYCODE_PROVIDER', 'nvidia')
    if override == 'environment':
        monkeypatch.setenv('ISYMOTRON_API_KEY', 'fixture-active-key')
    else:
        monkeypatch.setenv('ISYMOTRON_API_KEY_FILE', str(isolated_keys / 'missing'))
    assert load_api_key('openai') == ''


def test_explicit_provider_uses_own_store_despite_generic_file(isolated_keys, monkeypatch):
    monkeypatch.setenv('ISYCODE_PROVIDER', 'nvidia')
    monkeypatch.setenv('ISYMOTRON_API_KEY_FILE', str(isolated_keys / 'missing'))
    (isolated_keys / 'keys.env').write_text('OPENAI_API_KEY=fixture-openai-key\n', encoding='utf-8')
    assert load_api_key('openai') == 'fixture-openai-key'


@pytest.mark.parametrize('unsafe_state', ['corrupt', 'symlink', 'permissions', 'directory-symlink'])
def test_unsafe_authority_returns_denied_diagnostics_json(
        tmp_path, monkeypatch, capsys, unsafe_state):
    if unsafe_state == 'permissions' and os.name != 'posix':
        pytest.skip('POSIX policy permissions')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    authority = WorkspaceAuthority(workspace)
    if unsafe_state == 'directory-symlink':
        # Construct a separate unsafe state root without replacing the real one.
        unsafe_root = tmp_path / 'unsafe-state'
        unsafe_root.mkdir()
        (unsafe_root / 'workspace-authority').symlink_to(
            authority.state_directory, target_is_directory=True)
        monkeypatch.setenv('ISYCODE_STATE_HOME', str(unsafe_root))
    elif unsafe_state == 'symlink':
        target = tmp_path / 'outside-policy.json'
        target.write_text('sensitive-policy-content', encoding='utf-8')
        authority.policy_path.symlink_to(target)
    else:
        payload = (json.dumps({'version': authority.VERSION,
                               'workspace_root': str(authority.root),
                               'grants': {}, 'mode': 'classic'})
                   if unsafe_state == 'permissions' else '{broken-policy')
        authority.policy_path.write_text(payload, encoding='utf-8')
        authority.policy_path.chmod(0o644 if unsafe_state == 'permissions' else 0o600)
    report = json.loads(format_diagnostics(collect_diagnostics(workspace)))
    assert report['workspace_mode'] == 'unavailable; actions remain denied'
    assert report['enabled_actions'] == []
    assert report['network_tested'] is False
    assert 'sensitive-policy-content' not in json.dumps(report)
    assert main(['doctor', '--json']) == 0
    cli_report = json.loads(capsys.readouterr().out)
    assert cli_report['workspace_mode'] == report['workspace_mode']
    assert cli_report['enabled_actions'] == []
