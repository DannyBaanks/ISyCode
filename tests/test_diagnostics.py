import json

from isycode.diagnostics import collect_diagnostics
from isycode.launcher import main


def test_doctor_is_local_and_does_not_expose_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setenv('ISYCODE_PROVIDER', 'openai')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-this-value-must-not-appear')
    monkeypatch.setenv('ISYCODE_BASE_URL', 'https://user:password@example.com/v1?token=secret')
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network')))
    report = collect_diagnostics(tmp_path)
    serialized = json.dumps(report)
    for secret in ('sk-this-value', 'password', 'token=secret'):
        assert secret not in serialized
    assert report['network_tested'] is False
    assert report['provider']['credential'] == 'environment-present'
    assert report['provider']['endpoint'] == 'invalid-credential-bearing-url'


def test_doctor_cli_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    assert main(['doctor', '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['network_tested'] is False
    assert 'python' in report['dependencies']


def test_connection_check_binds_transport_settings(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from isycode.tui import TUIApp
    monkeypatch.setenv('ISYCODE_PROVIDER', 'openai')
    monkeypatch.setenv('ISYCODE_MODEL', 'gpt-6-luna')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-not-real')
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    captured = []
    class DeniedOwner:
        def __init__(self, *args):
            pass
        async def execute(self, provider, material, send):
            captured.append((provider, material))
            return None, SimpleNamespace(decision='DENY', reason='test denies network')
    monkeypatch.setattr('isycode.tui.ProviderNetworkOwner', DeniedOwner)
    monkeypatch.setattr('isycode.tui.load_provider_key', lambda name: None)
    app = SimpleNamespace(_workspace_root=tmp_path, _append=lambda *args: None)
    asyncio.run(TUIApp._check_provider_connection(app))
    provider, material = captured[0]
    assert material['token_limit_field'] == provider.token_limit_field
    assert material['reasoning_effort'] == provider.reasoning_effort
    assert material['temperature_supported'] == provider.temperature_supported
    assert material['max_tokens'] == 256 and material['tools'] is None
