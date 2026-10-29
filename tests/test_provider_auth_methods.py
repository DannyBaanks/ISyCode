import asyncio
from pathlib import Path

from isycode.provider_auth import ProviderAuthOwner, auth_methods
from isycode.approvals import ActionApprovalStore
from isycode.workspace_authority import WorkspaceAuthority


def test_auth_capabilities_do_not_invent_oauth():
    assert [m['id'] for m in auth_methods('openai')] == ['api_key', 'browser', 'device']
    assert [m['id'] for m in auth_methods('anthropic')] == ['api_key']
    assert [m['id'] for m in auth_methods('ollama')] == ['local']
    assert auth_methods('unknown') == []


def test_subscription_login_requires_grant_and_exact_approval(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    root = tmp_path / 'project'
    root.mkdir()
    executable = tmp_path / 'codex'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o700)
    authority = WorkspaceAuthority(root)
    approvals = ActionApprovalStore()
    calls = []
    class FakeConnector:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): calls.append('start'); return self
        async def start_login(self, method):
            return {'method': method, 'login_id': 'test', 'url': 'https://auth.openai.com/device', 'user_code': 'TEST-CODE'}
        async def wait_login(self, login_id): return True
        async def account(self): return {'authenticated': True, 'method': 'chatgpt', 'plan': 'plus'}
        async def close(self): calls.append('close')
    owner = ProviderAuthOwner(root, authority, approvals, executable=str(executable), connector_factory=FakeConnector)
    request = owner.request('login', 'device')
    async def scenario():
        assert (await owner.begin(request, None))[0].decision == 'DENY'
        assert not calls
        authority.set_grant('provider.authenticate', enabled=True, targets=['chatgpt'],
                            executables=[str(executable)], network_hosts=['auth.openai.com', 'chatgpt.com'])
        assert (await owner.begin(request, None))[0].decision == 'DENY'
        assert not calls
        approval = approvals.issue(request, ttl_seconds=30)
        outcome, challenge = await owner.begin(request, approval)
        assert outcome.decision == 'ALLOW' and challenge['user_code'] == 'TEST-CODE'
        assert outcome.receipt.verify(request, outcome.text)
        assert (await owner.finish())[0].decision == 'ALLOW'
        from isycode.action_audit import ActionAuditJournal
        assert ActionAuditJournal(root).verify().status == 'PASS'
    asyncio.run(scenario())


def test_auth_revocation_stops_active_connector(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    root = tmp_path / 'project'
    root.mkdir()
    executable = tmp_path / 'codex'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o700)
    authority = WorkspaceAuthority(root)
    authority.set_grant('provider.authenticate', enabled=True, targets=['chatgpt'],
                        executables=[str(executable)], network_hosts=['auth.openai.com', 'chatgpt.com'])
    approvals = ActionApprovalStore()
    closed = []
    class FakeConnector:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def start_login(self, method): return {'method': method, 'login_id': 'test', 'url': 'https://auth.openai.com/device'}
        async def close(self): closed.append(True)
    owner = ProviderAuthOwner(root, authority, approvals, executable=str(executable), connector_factory=FakeConnector)
    request = owner.request('login', 'device')
    async def scenario():
        assert (await owner.begin(request, approvals.issue(request, ttl_seconds=30)))[0].decision == 'ALLOW'
        authority.set_grant('provider.authenticate', enabled=False)
        assert (await owner.finish())[0].decision == 'DENY'
        assert closed
    asyncio.run(scenario())


def test_revocation_during_connector_initialization_prevents_login(tmp_path,monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME',str(tmp_path/'state'))
    root=tmp_path/'project';root.mkdir()
    executable=tmp_path/'codex';executable.write_text('#!/bin/sh\nexit 0\n');executable.chmod(0o700)
    authority=WorkspaceAuthority(root)
    authority.set_grant('provider.authenticate',enabled=True,targets=['chatgpt'],executables=[str(executable)],network_hosts=['auth.openai.com','chatgpt.com'])
    calls=[]
    class Peer:
        def __init__(self,*a,**k): pass
        async def __aenter__(self):
            authority.set_grant('provider.authenticate',enabled=False)
            return self
        async def start_login(self,method):
            calls.append('login');return {'method':method,'login_id':'id','url':'https://auth.openai.com/device'}
        async def close(self): calls.append('close')
    approvals=ActionApprovalStore()
    owner=ProviderAuthOwner(root,authority,approvals,executable=str(executable),connector_factory=Peer)
    request=owner.request('login','device')
    async def run():
        result,challenge=await owner.begin(request,approvals.issue(request))
        assert result.decision=='DENY' and challenge is None
        assert 'login' not in calls and 'close' in calls
    asyncio.run(run())
