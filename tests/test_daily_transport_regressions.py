"""Offline transport regressions: all HTTP traffic stays on loopback."""
import asyncio
import json

import pytest

from isycode.streaming import StreamError, async_stream_complete


def test_provider_error_event_is_failure_without_echoing_remote_secrets(monkeypatch):
    with pytest.raises(StreamError) as caught:
        local_completion(monkeypatch, [{'error': {'message': 'fixture-secret-do-not-log', 'code': 429}}, '[DONE]'])
    assert 'fixture-secret-do-not-log' not in str(caught.value)


def test_disconnected_tool_stream_is_not_a_successful_turn(monkeypatch):
    with pytest.raises(StreamError, match='incomplete'):
        local_completion(monkeypatch, [{'choices': [{'delta': {'tool_calls': [
            {'index': 0, 'id': 'call_fixture', 'function': {'name': 'workspace_write', 'arguments': '{}'}}]}}]}])


def local_completion(monkeypatch, events):
    monkeypatch.setattr('urllib.request.getproxies', lambda: {})

    async def scenario():
        async def handler(reader, writer):
            try:
                headers = await reader.readuntil(b'\r\n\r\n')
                length = next(int(line.split(b':', 1)[1]) for line in headers.split(b'\r\n')
                              if line.lower().startswith(b'content-length:'))
                await reader.readexactly(length)
                body = ''.join('data: ' + (event if isinstance(event, str) else json.dumps(event))
                               + '\n\n' for event in events).encode()
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode()
                             + b'\r\n\r\n' + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handler, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            return await async_stream_complete(f'http://127.0.0.1:{port}/v1', '', 'fixture', [],
                                               timeout_s=2)

    return asyncio.run(scenario())


def test_length_limited_openai_call_is_not_executable(monkeypatch):
    result = local_completion(monkeypatch, [
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call_fixture',
            'function': {'name': 'workspace_write', 'arguments': '{"path":"a","content":"partial"}'}}]},
            'finish_reason': 'length'}]}, '[DONE]'])
    assert result['finish_reason'] == 'length'
    assert result['tool_calls'] == []


def test_chat_transport_never_disables_stream_timeout(monkeypatch):
    from types import SimpleNamespace
    from isycode import chat_transport

    seen = {}

    async def fake_stream(*args, **kwargs):
        seen["timeout_s"] = kwargs.get("timeout_s", "default")
        return {"text": "ok", "tool_calls": []}

    monkeypatch.setattr(chat_transport, "async_stream_complete", fake_stream)
    provider = SimpleNamespace(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="test",
        model="mistralai/mistral-large-4-1t-a52b",
        token_limit_field="max_tokens",
        reasoning_effort=None,
        temperature_supported=True,
    )
    res = asyncio.run(chat_transport.provider_complete(provider, [{"role": "user", "content": "hi"}]))
    assert res["text"] == "ok"
    assert seen["timeout_s"] != None  # noqa: E711
