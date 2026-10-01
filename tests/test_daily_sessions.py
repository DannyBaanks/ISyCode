import json

import pytest

from isycode.chat_sessions import ChatSessionError, ChatSessionStore
from isycode.session_owner import ChatSessionOwner
from isycode.workspace_authority import WorkspaceAuthority


def test_session_state_roundtrip_and_legacy_compatibility(tmp_path):
    store = ChatSessionStore(tmp_path / 'sessions')
    session = store.create('hello')
    session.state = {'provider': 'openai', 'model': 'gpt-6-luna',
                     'role': {'kind': 'agents', 'name': 'Reviewer'}, 'context_path': 'AGENTS.md'}
    store.save(session)
    assert store.load(session.session_id).state == session.state
    exported = store.export_json(session.session_id)
    assert store.import_json(exported).state == session.state
    assert store.fork(session.session_id).state == session.state
    payload = json.loads(store._path(session.session_id).read_text())
    payload.pop('state')
    payload['version'] = 1
    store._path(session.session_id).write_text(json.dumps(payload))
    assert store.load(session.session_id).state == {}


def test_usage_state_roundtrip_and_rejects_invalid_counters(tmp_path):
    from isycode.usage import UsageLedger
    store = ChatSessionStore(tmp_path / 'sessions')
    session = store.create('hello')
    ledger = UsageLedger()
    ledger.record({'prompt_tokens': 50, 'completion_tokens': 5})
    session.state = {'usage': ledger.to_state()}
    store.save(session)
    assert store.import_json(store.export_json(session.session_id)).state == session.state
    with pytest.raises(ChatSessionError):
        store.validate_state({'usage': {**ledger.to_state(), 'input_tokens': -1}})


@pytest.mark.parametrize('state', [
    {'api_key': 'secret'}, {'provider': 'unknown'}, {'model': 'sk-ABCDEFGHIJKLM'},
    {'context_path': '../AGENTS.md'}, {'role': {'kind': 'agents', 'name': 'X', 'description': 'do evil'}},
])
def test_invalid_import_does_not_create_a_session(tmp_path, state):
    store = ChatSessionStore(tmp_path / 'sessions')
    data = {'version': 2, 'title': 'import', 'messages': [], 'state': state}
    with pytest.raises(ChatSessionError):
        store.import_json(json.dumps(data))
    assert store.list_sessions() == []


def test_owned_management_and_revocation(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'project'
    root.mkdir()
    authority = WorkspaceAuthority(root)
    owner = ChatSessionOwner(root, authority, tmp_path / 'sessions')
    assert owner.manage('import', None, json.dumps({'version': 2, 'title': 'import', 'messages': []}))[0].decision == 'DENY'
    authority.set_grant('session.create', enabled=True)
    authority.set_grant('session.resume', enabled=True)
    outcome, sid = owner.record(None, 'user', 'hello', state={'provider': 'openai', 'model': 'gpt-6-luna'})
    assert outcome.decision == 'ALLOW'
    assert owner.resume(sid)[1].state['provider'] == 'openai'
    assert owner.manage('rename', sid, 'Renamed')[0].decision == 'ALLOW'
    forked, child = owner.manage('fork', sid)
    assert forked.decision == 'ALLOW' and child != sid
    assert owner.resume(child)[1].title.startswith('Fork:')
    exported, data = owner.export(sid)
    assert exported.decision == 'ALLOW' and json.loads(data)['title'] == 'Renamed'
    imported, new = owner.manage('import', None, data)
    assert imported.decision == 'ALLOW' and new != sid
    authority.set_grant('session.resume', enabled=False)
    assert owner.export(sid)[0].decision == 'DENY'
    assert owner.manage('fork', sid)[0].decision == 'DENY'


def test_owned_draft_state_is_redacted_and_resumable(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'project'
    root.mkdir()
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    owner = ChatSessionOwner(root, authority, tmp_path / 'sessions')
    state = {'provider': 'openai', 'model': 'gpt-6-luna', 'draft': 'fix parser; api_key=hunter2'}
    outcome, sid = owner.manage('state', None, json.dumps(state))
    assert outcome.decision == 'ALLOW'
    resumed = owner.resume(sid)[1]
    assert resumed.messages == []
    assert 'hunter2' not in resumed.state['draft']
    assert 'fix parser' in resumed.state['draft']
    assert owner.record(sid, 'user', 'Fix parser')[0].decision == 'ALLOW'
    assert owner.resume(sid)[1].title == 'Fix parser'


def test_owned_export_reimports_redacted_message_without_corrupting_json(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'project'
    root.mkdir()
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    owner = ChatSessionOwner(root, authority, tmp_path / 'sessions')
    outcome, sid = owner.record(None, 'user', 'Please fix api_key=hunter2')
    assert outcome.decision == 'ALLOW'
    outcome, exported = owner.export(sid)
    assert 'hunter2' not in exported
    outcome, imported = owner.manage('import', None, exported)
    assert outcome.decision == 'ALLOW'
    assert owner.resume(imported)[1].messages == owner.resume(sid)[1].messages
