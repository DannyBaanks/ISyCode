"""Regression controls for the post-merge Hive audit."""
import asyncio
import json
from pathlib import Path

import pytest

from isycode.hive import HiveManager, HiveConfig, AgentMeta, MessageAct
from isycode.hive.router import Router
from isycode.hive.spawn import spawn_hive_agent


def hive(tmp_path):
    manager = HiveManager(HiveConfig(harness_home=tmp_path, auto_commit=False))
    for name in ('alice', 'bob'):
        manager.upsert_agent(AgentMeta(id=name, name=name, cwd=str(tmp_path)))
    return manager


@pytest.mark.asyncio
async def test_acknowledged_message_is_not_replayed_after_router_restart(tmp_path):
    manager = hive(tmp_path)
    msg = manager.send_message('alice', 'bob', MessageAct.INFORM, 'hello', 'body')
    await Router(manager.hive_root, manager.registry)._route_once()
    manager.mark_inbox_read('bob', [msg.id])
    assert manager.read_inbox('bob') == []
    assert len(manager.read_inbox('bob', include_done=True)) == 1
    await Router(manager.hive_root, manager.registry)._route_once()
    assert manager.read_inbox('bob') == []


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('id', '../escaped'), ('id', '/tmp/escaped'), ('from', 'mallory'), ('hops', -1), ('requires_reply', 'yes')])
async def test_router_rejects_untrusted_envelope(tmp_path, field, value):
    manager = hive(tmp_path)
    msg = manager.send_message('alice', 'bob', MessageAct.INFORM, 'hello', 'body')
    source = manager.agent_dir('alice') / 'outbox' / f'{msg.id}.json'
    envelope = json.loads(source.read_text())
    envelope[field] = value
    source.write_text(json.dumps(envelope))
    await Router(manager.hive_root, manager.registry)._route_once()
    assert manager.read_inbox('bob') == []
    assert not (manager.agent_dir('bob') / 'escaped.json').exists()


def test_write_guard_rejects_symlink_into_peer(tmp_path):
    manager = hive(tmp_path)
    link = manager.agent_dir('alice') / 'outbox' / 'peer'
    try:
        link.symlink_to(manager.agent_dir('bob'), target_is_directory=True)
    except OSError:
        pytest.skip('symlinks unavailable')
    decision = manager.check_write('Write', {'file_path': str(link / 'identity.md')}, str(tmp_path), 'alice')
    assert decision['deny']


@pytest.mark.asyncio
async def test_router_observes_agents_registered_after_start(tmp_path):
    manager = HiveManager(HiveConfig(harness_home=tmp_path, auto_commit=False))
    manager.ensure_hive()
    await manager.start_router()
    try:
        manager.upsert_agent(AgentMeta(id='alice', name='alice', cwd=str(tmp_path)))
        manager.upsert_agent(AgentMeta(id='bob', name='bob', cwd=str(tmp_path)))
        manager.send_message('alice', 'bob', MessageAct.INFORM, 'hello', 'body')
        await manager._router._route_once()
        assert len(manager.read_inbox('bob')) == 1
    finally:
        await manager.stop_router()


@pytest.mark.asyncio
async def test_unowned_external_spawn_fails_without_side_effects(tmp_path):
    manager = HiveManager(HiveConfig(harness_home=tmp_path))
    result = await spawn_hive_agent(manager, None, 'python3', 'do work', str(tmp_path))
    assert result.pid is None
    assert result.error
    assert not manager.hive_root.exists()


@pytest.mark.asyncio
async def test_hive_repair_uses_authorized_lane_with_exact_compose():
    from isycode.tui_app_sessions import SessionMixin
    class App:
        def __init__(self):
            self.messages = []
            self.briefs = []
        def _append(self, text, color):
            self.messages.append(text)
        async def _launch_repair_conversation(self, brief):
            self.briefs.append(brief)
    app = App()
    await SessionMixin._launch_hive_agent(app, 'exact repair task')
    assert app.briefs == ['exact repair task']


def test_generated_hook_runs_real_python_shim_from_spaced_directory(tmp_path):
    import os
    import shlex
    import subprocess
    manager = hive(tmp_path / 'with spaces')
    meta = AgentMeta(id='alice', name='Alice', provider='claude', cwd=str(tmp_path))
    injection = manager.build_spawn_injection(meta)
    settings = json.loads((manager.agent_dir('alice') / 'settings.json').read_text())
    command = settings['hooks']['PreToolUse'][0]['hooks'][0]['command']
    argv = command if os.name == 'nt' else shlex.split(command)
    result = subprocess.run(argv, input=json.dumps({'tool_name': 'Write', 'tool_input': {
        'file_path': str(manager.agent_dir('bob') / 'identity.md')}, 'cwd': str(tmp_path)}),
        text=True, capture_output=True, env={**os.environ, **injection.env}, timeout=5)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_unsupported_hook_provider_does_not_emit_trust_bypass(tmp_path):
    manager = HiveManager(HiveConfig(harness_home=tmp_path))
    with pytest.raises(ValueError, match='not supported'):
        manager.build_spawn_injection(AgentMeta(id='agent', name='agent', provider='codex'))
    assert not manager.hive_root.exists()


@pytest.mark.asyncio
async def test_router_does_not_overwrite_existing_inbox_message(tmp_path):
    manager = hive(tmp_path)
    msg = manager.send_message('alice', 'bob', MessageAct.INFORM, 'hello', 'original')
    router = Router(manager.hive_root, manager.registry)
    await router._route_once()
    archived = manager.agent_dir('alice') / 'outbox' / '.sent' / f'{msg.id}.json'
    envelope = json.loads(archived.read_text())
    envelope['body'] = 'replacement'
    (archived.parent.parent / archived.name).write_text(json.dumps(envelope))
    await router._route_once()
    assert manager.read_inbox('bob')[0].body == 'original'


@pytest.mark.asyncio
async def test_router_rejects_linked_recipient_inbox(tmp_path):
    manager = hive(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    # Register recipient without bootstrap so its first inbox can be a link.
    from isycode.hive.types import RegistryAgent
    carol = manager.agent_dir('carol')
    carol.mkdir()
    try:
        (carol / 'inbox').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlinks unavailable')
    msg = manager.send_message('alice', 'bob', MessageAct.INFORM, 'hello', 'body')
    source = manager.agent_dir('alice') / 'outbox' / f'{msg.id}.json'
    envelope = json.loads(source.read_text())
    manager.registry.agents['carol'] = RegistryAgent(id='carol', name='carol')
    envelope['to'] = 'carol'
    source.write_text(json.dumps(envelope))
    router = Router(manager.hive_root, lambda: manager.registry)
    await router._route_once()
    assert list(outside.iterdir()) == []


def test_agent_ids_cannot_escape_hive(tmp_path):
    manager = HiveManager(HiveConfig(harness_home=tmp_path))
    with pytest.raises(ValueError):
        manager.upsert_agent(AgentMeta(id='../escape', name='bad'))
    assert not (tmp_path / 'escape').exists()


def test_upsert_does_not_follow_linked_identity(tmp_path):
    manager = hive(tmp_path)
    # Use a new agent directory to avoid replacing any existing fixture file.
    directory = manager.agent_dir('carol')
    directory.mkdir()
    private = tmp_path / 'private.txt'
    private.write_text('untouched')
    try:
        (directory / 'identity.md').symlink_to(private)
    except OSError:
        pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError):
        manager.upsert_agent(AgentMeta(id='carol', name='carol'))
    assert private.read_text() == 'untouched'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', ['\n' * 200000, '\0' * 262144])
async def test_escaped_message_body_still_delivers_within_documented_limit(tmp_path, body):
    manager = hive(tmp_path)
    manager.send_message('alice', 'bob', MessageAct.INFORM, '\0' * 4096, body)
    await Router(manager.hive_root, manager.registry)._route_once()
    messages = manager.read_inbox('bob')
    assert len(messages) == 1
    assert messages[0].body == body


@pytest.mark.parametrize('registry', [[], {'agents': []}])
def test_malformed_registry_denies_instead_of_crashing_hook(tmp_path, registry):
    from isycode.hive.hook_shim import handle_pre_tool_use
    root = tmp_path / 'hive'
    root.mkdir()
    (root / 'registry.json').write_text(json.dumps(registry))
    response = handle_pre_tool_use({'tool_name': 'Write', 'tool_input': {
        'file_path': str(root / 'board.md')}, 'cwd': str(tmp_path)}, root, 'alice')
    assert response['hookSpecificOutput']['permissionDecision'] == 'deny'
