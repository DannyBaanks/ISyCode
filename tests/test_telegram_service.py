import asyncio
import json
from functools import partial

import pytest

from isycode.providers import Provider
from isycode.telegram.owner import Peer
from isycode.telegram.service import NativeRunner, TelegramService, native_sessions
from isycode.telegram.state import TelegramStore
from isycode.telegram.transport import SendReceipt, TelegramError
from isycode.workspace_authority import WorkspaceAuthority


class Transport:
    def __init__(self):
        self.sent = []
        self.offline = False
        self.edits = []
    async def get_me(self):
        return 123
    async def ensure_polling(self):
        pass
    async def get_updates(self, offset):
        await asyncio.sleep(0.01)
        return []
    async def send(self, chat, render):
        if self.offline:
            raise TelegramError('transport_failure')
        self.sent.append(render)
        return SendReceipt(chat, len(self.sent))

    async def edit(self, chat, message_id, render):
        if self.offline:
            raise TelegramError('transport_failure')
        self.edits.append((message_id, render))
        return SendReceipt(chat, message_id)


def update(i, text, user=456):
    return {'update_id': i, 'message': {'chat': {'type': 'private', 'id': user},
            'from': {'id': user, 'is_bot': False}, 'text': text}}


def callback(i, data, message_id):
    return {'update_id': i, 'callback_query': {'from': {'id': 456, 'is_bot': False},
            'data': data, 'message': {'chat': {'type': 'private', 'id': 456},
            'message_id': message_id, 'from': {'id': 123, 'is_bot': True}}}}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setattr('isycode.egress.review_destination', lambda url: None)
    root = tmp_path / 'project'
    root.mkdir()
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    peer = Peer('personal', 123, 456, 456)
    for action in ('telegram.connect', 'telegram.receive', 'telegram.send'):
        authority.set_grant(action, enabled=True, targets=[peer.target])
    store = TelegramStore('personal')
    store.set_setting('peer', {'bot_id': 123, 'user_id': 456, 'chat_id': 456})
    store.add_workspace('project', root)
    return store, root, authority, Transport()


async def wait_for(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(.01)
    raise AssertionError('condition not reached')


def test_native_session_fifo_edit_review_and_delivery_retry(setup):
    store, root, authority, transport = setup
    (root / 'file.txt').write_text('before')
    gate = asyncio.Event()
    turns = []
    async def provider(messages, tools, chunk):
        if messages[-1]['role'] == 'tool':
            chunk('content', 'edited')
            return {'text': 'edited'}
        prompt = messages[-1]['content']
        turns.append(prompt)
        if prompt == 'first':
            chunk('reasoning', 'checking')
            await gate.wait()
            return {'tool_calls': [{'id': 'edit1', 'function': {'name': 'workspace_edit',
                    'arguments': json.dumps({'path': 'file.txt', 'old_text': 'before', 'new_text': 'after'})}}]}
        return {'text': 'second answer'}
    factory = partial(NativeRunner, provider_factory=lambda *args: Provider(name='openai', api_key='fake'), transport=provider)
    service = TelegramService(store, transport, factory, pace=0)
    async def run():
        await service.handle_update(update(1, '/nueva project'))
        sid = service.selected
        assert sid
        await service.handle_update(update(2, 'first'))
        await service.work_once()
        await wait_for(lambda: turns == ['first'])
        await service.handle_update(update(3, 'second'))
        await service.handle_update(update(3, 'second'))
        await service.handle_update(update(4, 'intruder', user=999))
        await service.work_once()
        assert [row['state'] for row in store.queue()] == ['running', 'queued']
        gate.set()
        await wait_for(lambda: bool(service.callbacks))
        key, record = next(iter(service.callbacks.items()))
        await service.handle_update(callback(5, 'a:' + key, record[3] + 1))
        assert (root / 'file.txt').read_text() == 'before'
        await service.handle_update(callback(6, 'a:' + key, record[3]))
        await wait_for(lambda: store.queue()[0]['state'] == 'completed')
        assert (root / 'file.txt').read_text() == 'after'
        await service.work_once()
        await wait_for(lambda: store.queue()[1]['state'] == 'completed')
        assert turns == ['first', 'second']
        outcome, session = native_sessions(root, authority).resume(sid)
        assert outcome.decision == 'ALLOW'
        assert [m['content'] for m in session.messages] == ['first', 'edited', 'second', 'second answer']
        transport.offline = True
        await service.deliver_once()
        assert len(store.queue()) == 2
        with store.db() as db:
            assert db.execute('SELECT count(*) FROM events WHERE attempts>0 AND delivered=0').fetchone()[0] > 0
            db.execute('UPDATE events SET retry_at=0')
        transport.offline = False
        await service.deliver_once()
        assert not store.pending_deliveries()
        assert transport.edits and any("Turno finalizado" in rendered.text for _, rendered in transport.edits)
        await service.stop()
    asyncio.run(run())


def test_cancel_and_restart_never_replay_running_turn(setup):
    store, root, authority, transport = setup
    entered = asyncio.Event()
    class Runner:
        def __init__(self, *_): pass
        async def run(self):
            entered.set()
            await asyncio.Event().wait()
    service = TelegramService(store, transport, Runner, pace=0)
    async def run():
        await service.handle_update(update(1, '/nueva project'))
        await service.handle_update(update(2, 'first'))
        await service.handle_update(update(3, 'second'))
        await service.work_once()
        await entered.wait()
        await service.handle_update(update(4, '/cancelar'))
        await wait_for(lambda: store.queue()[0]['state'] == 'cancelled')
        await service.work_once()
        assert store.queue()[1]['state'] == 'queued'
        await service.stop()
        restarted = TelegramService(store, transport, Runner, pace=0)
        store.recover()
        await restarted.work_once()
        assert not restarted.active
        await restarted.handle_update(update(5, '/continuar'))
        await restarted.work_once()
        await wait_for(lambda: store.queue()[1]['state'] == 'running')
        await asyncio.sleep(0)
        await restarted.stop()
        assert [r['state'] for r in store.queue()] == ['cancelled', 'cancelled']
    asyncio.run(run())


def test_questions_rejection_native_reopen_and_divergence(setup):
    store, root, authority, transport = setup
    (root / 'file.txt').write_text('original')
    prompts = []
    async def provider(messages, tools, chunk):
        last = messages[-1]
        if last['role'] == 'user':
            return {'tool_calls': [{'id': 'question', 'function': {'name': 'ask_user', 'arguments': '{"question":"Which?"}'}}]}
        prompts.append(json.loads(last['content']))
        if last['tool_call_id'] == 'question':
            return {'tool_calls': [{'id': 'write', 'function': {'name': 'workspace_write', 'arguments': '{"path":"file.txt","content":"changed"}'}}]}
        return {'text': 'done'}
    factory = partial(NativeRunner, provider_factory=lambda *args: Provider(name='openai', api_key='fake'), transport=provider)
    service = TelegramService(store, transport, factory, pace=0)
    async def run():
        other = native_sessions(root, authority)
        outcome, sid = other.manage('state', None, '{}')
        assert outcome.decision == 'ALLOW'
        await service.handle_update(update(1, '/sesiones'))
        assert sid in transport.sent[-1].text
        await service.handle_update(update(2, '/usar ' + sid))
        await service.handle_update(update(3, 'work'))
        await service.work_once()
        await wait_for(lambda: bool(service.questions))
        identity = next(iter(service.questions))
        await service.handle_update(update(4, '/respuesta ' + identity + ' blue'))
        await wait_for(lambda: bool(service.callbacks))
        key, record = next(iter(service.callbacks.items()))
        await service.handle_update(callback(5, 'r:' + key, record[3]))
        await wait_for(lambda: store.queue()[0]['state'] == 'completed')
        assert prompts[0] == {'status': 'answered', 'text': 'blue'}
        assert (root / 'file.txt').read_text() == 'original'
        await service.handle_update(update(6, 'again'))
        await service.work_once()
        await wait_for(lambda: bool(service.questions))
        identity = next(iter(service.questions))
        await service.handle_update(update(7, '/respuesta ' + identity + ' green'))
        await wait_for(lambda: bool(service.callbacks))
        key, record = next(iter(service.callbacks.items()))
        outcome, _ = other.resume(sid)
        assert outcome.decision == 'ALLOW'
        outcome, _ = other.record(sid, 'user', 'external TUI change')
        assert outcome.decision == 'ALLOW'
        await service.handle_update(callback(8, 'a:' + key, record[3]))
        await wait_for(lambda: store.queue()[1]['state'] == 'interrupted')
        assert (root / 'file.txt').read_text() == 'original'
        outcome, session = other.resume(sid)
        assert session.messages[-1]['content'] == 'external TUI change'
        await service.stop()
    asyncio.run(run())


def test_two_workspaces_and_local_revocation(setup, tmp_path):
    store, root, authority, transport = setup
    second = tmp_path / 'second'
    second.mkdir()
    other = WorkspaceAuthority(second)
    other.set_mode('classic')
    for action in ('telegram.connect', 'telegram.receive', 'telegram.send'):
        other.set_grant(action, enabled=True, targets=[Peer('personal', 123, 456, 456).target])
    store.add_workspace('second', second)
    entered = []
    class Runner:
        def __init__(self, _, item): self.item = item
        async def run(self):
            entered.append(self.item.workspace)
            await asyncio.Event().wait()
    service = TelegramService(store, transport, Runner, pace=0)
    async def run():
        await service.handle_update(update(1, '/nueva project'))
        await service.handle_update(update(2, 'first'))
        await service.handle_update(update(3, 'queued'))
        await service.handle_update(update(4, '/nueva second'))
        await service.handle_update(update(5, 'parallel'))
        await service.work_once()
        await wait_for(lambda: len(entered) == 2)
        assert set(entered) == {root, second}
        store.revoke_pending()
        await service.work_once()
        await wait_for(lambda: all(row['state'] == 'cancelled' for row in store.queue()))
        await service.handle_update(update(6, 'not allowed'))
        assert len(store.queue()) == 3
        await service.stop()
    asyncio.run(run())


def test_native_flow_command_while_transport_disconnected_is_not_replayed(setup):
    import sys
    store, root, authority, transport = setup
    authority.set_mode('flow')
    authority.set_grant('provider.request', enabled=True, network_hosts=['api.openai.com'])
    calls = []
    marker = root / 'marker.txt'
    async def provider(messages, tools, chunk):
        if messages[-1]['role'] == 'tool':
            result = json.loads(messages[-1]['content'])
            assert result.get('receipt'), result
            assert 'tick' in str(result)
            return {'text': 'done'}
        calls.append('provider')
        return {'tool_calls': [{'id': 'command', 'function': {'name': 'workspace_run', 'arguments': json.dumps({
            'argv': [sys.executable, '-c', "import pathlib,time; p=pathlib.Path('marker.txt'); p.write_text((p.read_text() if p.exists() else '')+'once'); print('tick', flush=True); time.sleep(.3)"], 'cwd': str(root), 'timeout_s': 10})}}]}
    factory = partial(NativeRunner, provider_factory=lambda *args: Provider(name='openai', api_key='fake'), transport=provider)
    service = TelegramService(store, transport, factory, pace=0)
    async def run():
        await service.handle_update(update(1, '/nueva project'))
        await service.handle_update(update(2, 'execute controlled command'))
        await service.work_once()
        await wait_for(marker.exists)
        transport.offline = True
        await service.deliver_once()
        await wait_for(lambda: store.queue()[0]['state'] == 'completed')
        assert marker.read_text() == 'once'
        await service.stop()
        restarted = TelegramService(store, transport, factory, pace=0)
        store.recover()
        await restarted.work_once()
        assert not restarted.active and calls == ['provider']
        assert marker.read_text() == 'once'
        await restarted.stop()
    asyncio.run(run())


def test_start_foreground_lock_identity_and_stop(setup):
    store, root, authority, transport = setup
    service = TelegramService(store, transport, pace=0)
    async def run():
        await service.start()
        assert service.running
        with pytest.raises((OSError, ValueError)):
            await TelegramService(store, transport, pace=0).start()
        store.set_setting('stop_requested', True)
        await wait_for(lambda: not service.running)
        await service.stop()
        class Wrong(Transport):
            async def get_me(self): return 999
        with pytest.raises(PermissionError):
            await TelegramService(store, Wrong(), pace=0).start()
        with store.service_lock(): pass
    asyncio.run(run())
