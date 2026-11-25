import asyncio

import pytest

from isycode.credentials import CredentialVaultError
from isycode.telegram.cli import configure, is_running, main, verify_pairing
from isycode.telegram.state import TelegramStore
from isycode.telegram.transport import TelegramError
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    return TelegramStore('personal')


class PairTransport:
    async def get_me(self): return 123
    async def ensure_polling(self): pass
    async def get_updates(self, offset):
        def msg(i, user, kind, text):
            return {'update_id': i, 'message': {'chat': {'id': user, 'type': kind},
                    'from': {'id': user, 'is_bot': False}, 'text': text}}
        pin = '/pair ' + 'ab' * 6
        return [msg(1, 999, 'private', pin), msg(2, 456, 'group', pin),
                msg(3, 456, 'private', '/pair wrong'), msg(4, 456, 'private', pin)] if offset == 0 else []


class Vault:
    def __init__(self): self.values = {}
    def add(self, name, service, purpose, secret):
        self.values['cred_' + '1' * 16] = secret
        return 'cred_' + '1' * 16


def test_expected_private_user_and_pin_only(store, monkeypatch):
    monkeypatch.setattr('isycode.telegram.cli.secrets.token_hex', lambda _: 'ab' * 6)
    peer = asyncio.run(verify_pairing(store, PairTransport(), 456, show=lambda _: None))
    assert peer.user_id == 456 and peer.bot_id == 123
    assert store.cursor() == 5
    with store.db() as db:
        assert [r[0] for r in db.execute('SELECT disposition FROM updates ORDER BY id')] == ['rejected'] * 3 + ['accepted']


def test_configure_requires_keyring_and_never_starts(store, tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    def unavailable(): raise CredentialVaultError('no secure backend')
    with pytest.raises(CredentialVaultError):
        asyncio.run(configure(store, root, 'main', 456, vault_factory=unavailable,
                    transport_factory=lambda _: pytest.fail('network before vault')))
    monkeypatch.setattr('isycode.telegram.cli.secrets.token_hex', lambda _: 'ab' * 6)
    vault = Vault()
    token = '123456:' + 'x' * 35
    asyncio.run(configure(store, root, 'main', 456, vault_factory=lambda: vault,
                transport_factory=lambda _: PairTransport(), consent=lambda _: True, secret_input=lambda _: token))
    assert not is_running(store) and store.setting('peer')['user_id'] == 456
    assert authority.mode() == 'classic'
    assert vault.values[store.setting('credential_id')] == token
    for path in store.directory.iterdir():
        if path.is_file(): assert token.encode() not in path.read_bytes()
    assert main(['status']) == 0
    assert main(['stop']) == 0 and store.setting('stop_requested') is True


def test_lock_reports_owned_instance_and_rejects_duplicate(store):
    assert not is_running(store)
    with store.service_lock():
        assert is_running(store)
        with pytest.raises((BlockingIOError, PermissionError)):
            with store.service_lock(): pass
    assert not is_running(store)
