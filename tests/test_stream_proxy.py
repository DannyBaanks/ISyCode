import asyncio
import json
from types import SimpleNamespace

import pytest

from isycode.streaming import StreamError, async_stream_complete


@pytest.mark.parametrize("provider_name", ["openai", "nvidia", "local", "nebius"])
def test_provider_usage_options_and_final_usage_over_local_sse(monkeypatch, provider_name):
    from isycode.chat_transport import provider_complete

    monkeypatch.setattr("urllib.request.getproxies", lambda: {})

    async def scenario():
        received = []

        async def server_handler(reader, writer):
            headers = await reader.readuntil(b"\r\n\r\n")
            content_length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                                  if line.lower().startswith(b"content-length:"))
            received.append(json.loads(await reader.readexactly(content_length)))
            body = (b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n'
                    b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3}}\n\n'
                    b"data: [DONE]\n\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(server_handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        provider = SimpleNamespace(name=provider_name, base_url=f"http://127.0.0.1:{port}/v1",
                                   api_key="", model="fixture", token_limit_field="max_tokens",
                                   reasoning_effort=None, temperature_supported=True)
        async with server:
            result = await provider_complete(provider, [], max_tokens=7)
        assert result["text"] == "OK"
        assert result["usage"] == {"prompt_tokens": 12, "completion_tokens": 3}
        assert received[0]["max_tokens"] == 7
        if provider_name in {"openai", "nvidia"}:
            assert received[0]["stream_options"] == {"include_usage": True}
        else:
            assert "stream_options" not in received[0]

    asyncio.run(scenario())


def _proxy_listener():
    received = []

    async def proxy(reader, writer):
        received.append(await reader.read(256))
        writer.close()
        await writer.wait_closed()

    return received, proxy


def test_http_proxy_sends_nothing(monkeypatch):
    async def scenario():
        received, proxy = _proxy_listener()
        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr("urllib.request.getproxies", lambda: {"http": f"http://127.0.0.1:{port}"})
        async with server:
            with pytest.raises(StreamError, match="ambient proxy") as caught:
                await async_stream_complete(
                    "http://example.invalid/v1", "private-test-key", "local", [], timeout_s=2)
            await asyncio.sleep(0)
        assert received == []
        assert "private-test-key" not in str(caught.value)
        assert str(port) not in str(caught.value)
    asyncio.run(scenario())


def test_https_proxy_denial_never_sends_provider_key(monkeypatch):
    async def scenario():
        received, proxy = _proxy_listener()
        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr("urllib.request.getproxies", lambda: {"https": f"http://127.0.0.1:{port}"})
        async with server:
            with pytest.raises(StreamError, match="ambient proxy") as caught:
                await async_stream_complete(
                    "https://example.invalid/v1", "private-test-key", "local", [], timeout_s=2)
            await asyncio.sleep(0)
        assert received == []
        assert "private-test-key" not in str(caught.value)
    asyncio.run(scenario())


def test_https_proxy_tunnel_is_not_opened(monkeypatch):
    """An ambient proxy is a different destination, so no CONNECT and no key leave."""
    async def scenario():
        received, proxy = _proxy_listener()
        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr("urllib.request.getproxies", lambda: {"https": f"http://127.0.0.1:{port}"})
        async with server:
            with pytest.raises(StreamError, match="ambient proxy") as caught:
                await async_stream_complete(
                    "https://provider.invalid/v1", "private-test-key", "local", [], timeout_s=2)
            await asyncio.sleep(0)
        assert received == []
        text = str(caught.value)
        assert "private-test-key" not in text and "CONNECT" not in text
    asyncio.run(scenario())


def test_cancel_during_connect_closes_proxy_socket(monkeypatch):
    async def scenario():
        started = asyncio.Event()

        async def proxy(reader, writer):
            started.set()
            await reader.read(64)
            writer.close()

        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr("urllib.request.getproxies", lambda: {"https": f"http://127.0.0.1:{port}"})
        async with server:
            with pytest.raises(StreamError, match="ambient proxy"):
                await async_stream_complete(
                    "https://example.invalid/v1", "private-test-key", "local", [], timeout_s=2)
            await asyncio.sleep(0)
        assert not started.is_set()
    asyncio.run(scenario())


def test_no_proxy_keeps_local_provider_off_external_proxy(monkeypatch):
    async def scenario():
        async def provider(reader, writer):
            request = await reader.readuntil(b"\r\n\r\n")
            assert request.startswith(b"POST /v1/chat/completions HTTP/1.1")
            body = b'data: {"choices":[{"delta":{"content":"local"}}]}\n\ndata: [DONE]\n\n'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(provider, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
        monkeypatch.setattr("urllib.request.getproxies", lambda: {"http": "http://external.invalid:1"})
        async with server:
            result = await async_stream_complete(f"http://127.0.0.1:{port}/v1", "", "local", [], timeout_s=2)
        assert result["text"] == "local"
    asyncio.run(scenario())


def test_connect_rejects_plaintext_response_injection(monkeypatch):
    async def scenario():
        received = []

        async def proxy(reader, writer):
            received.append(await reader.read(256))
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n"
                         b"HTTP/1.1 200 OK\r\nContent-Length: 80\r\n\r\n"
                         b'data: {"choices":[{"delta":{"content":"FORGED"}}]}\n\n')
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr("urllib.request.getproxies", lambda: {"https": f"http://127.0.0.1:{port}"})
        chunks = []
        async with server:
            with pytest.raises(StreamError, match="ambient proxy"):
                await async_stream_complete(
                    "https://example.invalid/v1", "private-test-key", "local", [], timeout_s=2,
                    on_chunk=lambda *args: chunks.append(args))
            await asyncio.sleep(0)
        assert received == []
        assert chunks == []
    asyncio.run(scenario())
