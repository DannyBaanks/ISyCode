from dataclasses import replace

import pytest

from isycode.agent_tools import ReviewMaterial, policy_fingerprint
from isycode.security import ActionRequest
from isycode.telegram.owner import Peer, RemoteReviews, ReviewContext, TelegramOwner
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'root'
    root.mkdir()
    authority = WorkspaceAuthority(root)
    return root, authority, Peer('personal', 123, 456, 456)


@pytest.mark.parametrize('mode', ['security', 'classic', 'flow'])
def test_integration_is_explicit_and_peer_bound(setup, mode):
    root, authority, peer = setup
    authority.set_mode(mode)
    owner = TelegramOwner(root, authority)
    for action in ('telegram.connect', 'telegram.receive', 'telegram.send'):
        with pytest.raises(PermissionError):
            owner.authorize(action, peer)
        authority.set_grant(action, enabled=True, targets=[peer.target])
        request = owner.authorize(action, peer, b'payload')
        assert request.target == peer.target
        assert owner.receipt(request, b'ok').verify(request, 'ok')
        with pytest.raises(PermissionError):
            owner.authorize(action, replace(peer, profile='other'))
        authority.set_grant(action, enabled=False)
        with pytest.raises(PermissionError):
            owner.authorize(action, peer)


def test_private_sender_and_forwarded_content(setup):
    _, _, peer = setup
    message = {'chat': {'id': 456, 'type': 'private'}}
    sender = {'id': 456, 'is_bot': False}
    assert peer.accepts(message, sender)
    assert not peer.accepts(message, {'id': 999, 'is_bot': False})
    assert not peer.accepts({'chat': {'id': 456, 'type': 'group'}}, sender)
    assert not peer.accepts({**message, 'forward_origin': {}}, sender)
    assert not peer.accepts(message, {'id': 456, 'is_bot': True})


def test_review_requires_full_material_and_current_identity(setup):
    root, authority, peer = setup
    authority.set_mode('classic')
    request = ActionRequest('workspace.files.write', root, str(root / 'file'), {}, execution_owner='workspace_write')
    fingerprint = policy_fingerprint(authority)
    context = ReviewContext(peer, root, 'a' * 32, 'b' * 32, fingerprint)
    material = ReviewMaterial(request.digest, 'complete diff', 'write', fingerprint)
    now = [0]
    reviews = RemoteReviews(clock=lambda: now[0], ttl=10)
    pending = reviews.open(context, material)
    assert not reviews.mark_delivered(pending.callback_id, 'wrong')
    assert not reviews.resolve(pending.callback_id, context, True, request=request, authority=authority)
    pending = reviews.open(context, material)
    assert reviews.mark_delivered(pending.callback_id, pending.material_digest)
    assert not reviews.resolve(pending.callback_id, replace(context, turn_id='c' * 32), True, request=request, authority=authority)
    assert reviews.resolve(pending.callback_id, context, True, request=request, authority=authority)
    assert not reviews.resolve(pending.callback_id, context, True, request=request, authority=authority)
    pending = reviews.open(context, material)
    assert reviews.mark_delivered(pending.callback_id, pending.material_digest)
    now[0] = 11
    assert not reviews.resolve(pending.callback_id, context, True, request=request, authority=authority)
    pending = reviews.open(context, material)
    assert reviews.mark_delivered(pending.callback_id, pending.material_digest)
    authority.set_mode('security')
    assert not reviews.resolve(pending.callback_id, context, True, request=request, authority=authority)
    assert not RemoteReviews().resolve(pending.callback_id, context, True, request=request, authority=authority)


def test_telegram_credentials_exact_id_no_implicit_grant(setup):
    from isycode.credential_owner import CredentialOwner, CredentialUseOwner
    from isycode.approvals import ActionApprovalStore
    root, authority, _ = setup
    authority.set_mode('classic')
    class Vault:
        def __init__(self):
            self.rows = []
            self.secrets = {}
        def add(self, name, service, purpose, secret):
            key = 'cred_' + f'{len(self.rows):016x}'
            self.rows.append({'id': key, 'service': service, 'revoked': False})
            self.secrets[key] = secret
            return key
        def list_metadata(self):
            return self.rows
        def get_secret(self, key):
            return self.secrets[key]
    vault = Vault()
    approvals = ActionApprovalStore()
    save = CredentialOwner(root, authority, approvals, vault=vault)
    use = CredentialUseOwner(root, authority, vault=vault)
    service = 'isycode-telegram'
    request = save.add_request(service, 'first', 'personal bot')
    assert save.add(request, 'synthetic-first', approvals.issue(request)).decision == 'DENY'
    authority.set_grant('credentials.add', enabled=True, targets=[service])
    keys = []
    for value in ('synthetic-first', 'synthetic-second'):
        outcome = save.add(request, value, approvals.issue(request))
        assert outcome.decision == 'ALLOW'
        keys.append(outcome.reason)
    assert use.secret_for(service, 'telegram', key_id=keys[0])[1] is None
    authority.set_grant('credentials.use', enabled=True, targets=[service])
    assert use.secret_for(service, 'telegram', key_id=keys[0])[1] == 'synthetic-first'
    assert use.secret_for(service, 'telegram', key_id=keys[1])[1] == 'synthetic-second'
    assert use.secret_for(service, 'provider.request', key_id=keys[0])[1] is None
    assert use.secret_for(service, 'telegram')[1] is None
