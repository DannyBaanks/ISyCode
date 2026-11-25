import asyncio
import json

import pytest

from isycode.agent_runtime import AgentTurn, TurnPorts
from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.providers import Provider
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture
def native_root(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setattr('isycode.egress.review_destination', lambda url: None)
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'value.txt').write_text('forty-two')
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    return root, authority


def test_native_round_trip_emits_reasoning_and_preserves_real_tool_result(native_root):
    root, authority = native_root
    events = []
    calls = []
    async def transport(messages, tools, chunk):
        calls.append(list(messages))
        if len(calls) == 1:
            chunk('reasoning', 'I will inspect the file.')
            return {'text': '', 'tool_calls': [{'id': 'read1', 'function': {
                'name': 'workspace_read', 'arguments': '{"path":"value.txt"}'}}]}
        chunk('content', 'It says forty-two.')
        return {'text': 'It says forty-two.', 'tool_calls': []}
    async def dispatch(call):
        args = json.loads(call['function']['arguments'])
        result = LocalWorkspaceReadOwner(root, authority).execute('workspace.files.read', args)
        assert result.decision == 'ALLOW' and result.receipt
        return call['id'], result.text
    messages = [{'role': 'user', 'content': 'read it'}]
    result = asyncio.run(AgentTurn(root, authority).run(
        messages, provider=Provider(name='openai', api_key='fake'), tools=[],
        ports=TurnPorts(lambda kind, payload: events.append((kind, payload)), dispatch),
        transport=transport))
    assert result.text == 'It says forty-two.'
    assert calls[1][-1]['tool_call_id'] == 'read1'
    assert 'forty-two' in calls[1][-1]['content']
    assert [kind for kind, _ in events] == [
        'turn.start', 'provider.request', 'reasoning', 'provider.result',
        'tool.start', 'tool.result', 'provider.request', 'content', 'provider.result', 'turn.finish']
    assert len(result.provider_receipts) == 2


def test_denied_provider_never_calls_transport(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'project'
    root.mkdir()
    async def transport(*args):
        raise AssertionError('must not send')
    async def dispatch(call):
        raise AssertionError('must not dispatch')
    with pytest.raises(PermissionError):
        asyncio.run(AgentTurn(root, WorkspaceAuthority(root)).run(
            [{'role': 'user', 'content': 'hi'}], provider=Provider(name='openai', api_key='fake'),
            tools=[], ports=TurnPorts(lambda *args: None, dispatch), transport=transport))


def test_cancellation_keeps_completed_tool_protocol(native_root):
    root, authority = native_root
    messages = [{'role': 'user', 'content': 'work'}]
    count = 0
    async def transport(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise asyncio.CancelledError()
        return {'text': '', 'tool_calls': [{'id': 'once', 'function': {'name': 'read', 'arguments': '{}'}}]}
    async def dispatch(call):
        return 'once', 'verified result'
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(AgentTurn(root, authority).run(
            messages, provider=Provider(name='openai', api_key='fake'), tools=[],
            ports=TurnPorts(lambda *args: None, dispatch), transport=transport))
    assert messages[-1] == {'role': 'tool', 'tool_call_id': 'once', 'content': 'verified result'}
