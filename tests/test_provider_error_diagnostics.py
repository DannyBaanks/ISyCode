import asyncio
import json
import pytest
from isycode.provider_errors import classify_provider_error, error_signals
from isycode.streaming import StreamError, async_stream_complete

@pytest.mark.parametrize("status, code, expected", [(401, None, "APIKEY"), (402, None, "QUOTA"), (429, "insufficient_quota", "QUOTA"), (429, "rate_limit_exceeded", "RATE_LIMIT"), (404, "model_not_found", "MODEL"), (503, None, "PROVIDER")])
def test_exact_classification_without_secret_body(status, code, expected):
    exc = StreamError("fictional-secret", status, provider_code=code)
    detail = classify_provider_error(exc)
    assert detail["error_kind"] == expected
    assert "fictional-secret" not in json.dumps(detail)


def test_quota_code_and_retry_after_survive_actual_http_error():
    async def scenario():
        async def serve(reader, writer):
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length:"))
            await reader.readexactly(length)
            body = json.dumps({"error": {"code": "insufficient_quota", "message": "Bearer secret-do-not-echo"}}).encode()
            writer.write(b"HTTP/1.1 429 Too Many Requests\r\nRetry-After: 7\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            with pytest.raises(StreamError) as caught:
                await async_stream_complete(f"http://127.0.0.1:{port}/v1", "", "fixture", [], timeout_s=2)
        detail = classify_provider_error(caught.value)
        assert detail["error_kind"] == "QUOTA" and detail["retry_after_s"] == 7
        assert "secret-do-not-echo" not in str(caught.value)
    asyncio.run(scenario())


def test_subagent_failure_reopens_selector_before_any_new_request(tmp_path, monkeypatch):
    from test_daily_tui import configure
    from isycode.tui import TUIApp, plain_text
    from isycode.providers import save_provider_selection
    from isycode.subagent_screen import SubagentModelScreen
    root = configure(tmp_path, monkeypatch)
    from isycode.workspace_authority import WorkspaceAuthority
    WorkspaceAuthority(root).set_grant("provider.request", enabled=True, network_hosts=["integrate.api.nvidia.com"])
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "fixture-not-real")
    save_provider_selection("nvidia", "child-model")
    calls = []
    async def complete(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise StreamError("safe failure", 429, provider_code="insufficient_quota")
        return {"text": "Recovered child", "tool_calls": []}
    monkeypatch.setattr("isycode.tui.provider_complete", complete)
    async def wait_screen(app, pilot, error):
        for _ in range(200):
            await pilot.pause(.01)
            if isinstance(app.screen, SubagentModelScreen) and bool(app.screen.error) == error:
                await app.screen.ready.wait()
                await pilot.pause(.1)
                return
        pytest.fail(f"selector did not reopen: calls={len(calls)}, screen={type(app.screen).__name__}, running={app._subagent_running}, title={app._child_title}")
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._run_subagent("inspect"))
            await wait_screen(app, pilot, False)
            await pilot.click("#child-launch")
            await wait_screen(app, pilot, True)
            assert app.screen.error["error_kind"] == "QUOTA"
            assert len(calls) == 1 and not task.done()
            assert "billing restriction" in plain_text(app.screen.query_one("#child-error"))
            await pilot.click("#child-launch")
            result = await asyncio.wait_for(task, 5)
            assert result["status"] == "completed" and len(calls) == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("body, expected", [
    (b"data: " + b"x" * (2 * 1024 * 1024), "exceeds 1 MiB"),
    (b'data: {"error": {"code": "invalid_api_key", "message": "Bearer secret-do-not-echo"}}\n\n', "streaming API error"),
])
def test_sync_stream_has_the_async_bounds_and_error_events(body, expected):
    """Hermes audit 2026-10-08, finding 8: the sync SSE path lacked the async hardening."""
    import http.server
    import threading
    from isycode.streaming import stream_complete

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(StreamError, match=expected) as caught:
            stream_complete(f"http://127.0.0.1:{server.server_port}/v1", "", "fixture", [], timeout_s=5)
        assert "secret-do-not-echo" not in str(caught.value)
    finally:
        server.shutdown()
