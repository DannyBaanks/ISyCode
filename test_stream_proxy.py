import asyncio

import pytest

from isycode.streaming import StreamError, async_stream_complete


def test_http_proxy_streams_sse_and_uses_absolute_target(monkeypatch):
    async def scenario():
        received = []
        async def proxy(reader, writer):
            received.append(await reader.readuntil(b'\r\n\r\n'))
            data = b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(data)).encode() + b'\r\n\r\n' + data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(proxy, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr('urllib.request.getproxies', lambda: {'http': f'http://127.0.0.1:{port}'})
        async with server:
            result = await async_stream_complete('http://example.invalid/v1', '', 'local', [], timeout_s=2)
        assert result['text'] == 'OK'
        assert received[0].startswith(b'POST http://example.invalid/v1/chat/completions HTTP/1.1')
    asyncio.run(scenario())


def test_https_proxy_denial_never_sends_provider_key(monkeypatch):
    async def scenario():
        received = []
        async def proxy(reader, writer):
            received.append(await reader.readuntil(b'\r\n\r\n'))
            writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            assert await reader.read() == b''
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(proxy, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr('urllib.request.getproxies', lambda: {'https': f'http://127.0.0.1:{port}'})
        async with server:
            with pytest.raises(StreamError, match='proxy refused.*403'):
                await async_stream_complete('https://example.invalid/v1', 'private-test-key', 'local', [], timeout_s=2)
            await asyncio.sleep(0)
        assert received[0].startswith(b'CONNECT example.invalid:443 HTTP/1.1')
        assert b'private-test-key' not in received[0]
    asyncio.run(scenario())


def test_https_proxy_tunnel_preserves_verified_tls(tmp_path, monkeypatch):
    import ssl
    import subprocess
    import shutil
    if not shutil.which('openssl'):
        pytest.skip('openssl required for local TLS fixture')
    key, cert = tmp_path / 'key.pem', tmp_path / 'cert.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=provider.invalid', '-addext', 'subjectAltName=DNS:provider.invalid',
                    '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(cert, key)
    client_tls = ssl.create_default_context(cafile=str(cert))
    assert client_tls.check_hostname and client_tls.verify_mode == ssl.CERT_REQUIRED
    monkeypatch.setattr('isycode.streaming.ssl.create_default_context', lambda: client_tls)
    async def scenario():
        received = []
        async def provider(reader, writer):
            received.append(await reader.readuntil(b'\r\n\r\n'))
            body = b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        upstream = await asyncio.start_server(provider, '127.0.0.1', 0, ssl=server_tls)
        upstream_port = upstream.sockets[0].getsockname()[1]
        async def proxy(reader, writer):
            received.append(await reader.readuntil(b'\r\n\r\n'))
            remote_reader, remote_writer = await asyncio.open_connection('127.0.0.1', upstream_port)
            writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
            await writer.drain()
            async def relay(source, target):
                while True:
                    data = await source.read(65536)
                    if not data:
                        break
                    target.write(data)
                    await target.drain()
                target.close()
            await asyncio.gather(relay(reader, remote_writer), relay(remote_reader, writer))
        server = await asyncio.start_server(proxy, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr('urllib.request.getproxies', lambda: {'https': f'http://127.0.0.1:{port}'})
        async with upstream, server:
            result = await async_stream_complete('https://provider.invalid/v1', 'private-test-key', 'local', [], timeout_s=3)
        assert result['text'] == 'OK'
        assert b'private-test-key' not in received[0]
        assert b'Authorization: Bearer private-test-key' in received[1]
    asyncio.run(scenario())


def test_cancel_during_connect_closes_proxy_socket(monkeypatch):
    async def scenario():
        started, closed = asyncio.Event(), asyncio.Event()
        async def proxy(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            started.set()
            assert await reader.read() == b''
            writer.close()
            await writer.wait_closed()
            closed.set()
        server = await asyncio.start_server(proxy, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr('urllib.request.getproxies', lambda: {'https': f'http://127.0.0.1:{port}'})
        async with server:
            task = asyncio.create_task(async_stream_complete('https://example.invalid/v1', 'private-test-key', 'local', []))
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(closed.wait(), 2)
    asyncio.run(scenario())


def test_no_proxy_keeps_local_provider_off_external_proxy(monkeypatch):
    async def scenario():
        async def provider(reader, writer):
            request = await reader.readuntil(b'\r\n\r\n')
            assert request.startswith(b'POST /v1/chat/completions HTTP/1.1')
            body = b'data: {"choices":[{"delta":{"content":"local"}}]}\n\ndata: [DONE]\n\n'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(provider, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
        monkeypatch.setenv('no_proxy', '127.0.0.1,localhost')
        monkeypatch.setattr('urllib.request.getproxies', lambda: {'http': 'http://external.invalid:1'})
        async with server:
            result = await async_stream_complete(f'http://127.0.0.1:{port}/v1', '', 'local', [], timeout_s=2)
        assert result['text'] == 'local'
    asyncio.run(scenario())


def test_connect_rejects_plaintext_response_injection(monkeypatch):
    async def scenario():
        closed = asyncio.Event()
        async def proxy(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n'
                         b'HTTP/1.1 200 OK\r\nContent-Length: 80\r\n\r\n'
                         b'data: {"choices":[{"delta":{"content":"FORGED"}}]}\n\n')
            await writer.drain()
            assert await reader.read() == b''
            writer.close()
            await writer.wait_closed()
            closed.set()
        server = await asyncio.start_server(proxy, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr('urllib.request.getproxies', lambda: {'https': f'http://127.0.0.1:{port}'})
        chunks = []
        async with server:
            with pytest.raises(StreamError, match='unexpected plaintext'):
                await async_stream_complete('https://example.invalid/v1', 'private-test-key', 'local', [], timeout_s=2,
                                            on_chunk=lambda *args: chunks.append(args))
            await asyncio.wait_for(closed.wait(), 2)
        assert chunks == []
    asyncio.run(scenario())
