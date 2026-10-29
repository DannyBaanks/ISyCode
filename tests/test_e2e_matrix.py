"""E2E matrix: the same edit journey through Classic, Flow and Security.

The matrix itself lives in ``docs/testing/e2e-matrix.md``. The other
dimensions (sizes, locales, providers, network failures, extra folders) have
focused tests there. This file covers the cross-dimension journey that had no
app-level test: the real TUI, authority and write owner in each mode.

Classic asks before the diff; Flow runs recoverable local work quietly;
Security does not even offer the write tool.
"""
import asyncio
import json

import pytest

from isycode.tui import TUIApp, WriteApprovalScreen
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure


EDIT = {"path": "app.py", "old_text": "value = 1", "new_text": "value = 2"}


@pytest.mark.parametrize("mode, expected", [
    ("classic", "asks"),
    ("flow", "quiet"),
    ("security", "denied"),
])
def test_the_same_edit_asks_in_classic_runs_quiet_in_flow_and_is_denied_in_security(
        tmp_path, monkeypatch, capsys, mode, expected):
    root = configure(tmp_path, monkeypatch)
    WorkspaceAuthority(root).set_mode(mode)
    (root / "app.py").write_text("value = 1\n")
    seen_tools = []
    screens = []
    calls = []
    lane_lines = []

    async def complete(provider, messages, **kwargs):
        offered = [tool["function"]["name"] for tool in (kwargs.get("tools") or [])]
        seen_tools.append(offered)
        calls.append(messages)
        if expected == "denied":
            assert "workspace_edit" not in offered
            return {"text": "No write tool is available.", "tool_calls": []}
        assert "workspace_edit" in offered
        if not any(message.get("role") == "tool" for message in messages):
            return {"text": "", "tool_calls": [{
                "id": "c0",
                "type": "function",
                "function": {"name": "workspace_edit", "arguments": json.dumps(EDIT)},
            }]}
        return {"text": "Changed value to 2.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        startup = app._startup_workspace

        async def no_startup():
            return None

        # Same isolation as test_daily_tui: the onboarding worker must not
        # contend for the action journal while the fake provider steps.
        app._startup_workspace = no_startup
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._startup_workspace = startup
            task = asyncio.create_task(app._run_chat("Change value to 2."))
            approved = False
            try:
                for _ in range(80):
                    await pilot.pause(0.05)
                    if isinstance(app.screen, WriteApprovalScreen):
                        screens.append(type(app.screen).__name__)
                        if not approved:
                            approved = True
                            await pilot.press("tab", "enter")
                    if task.done():
                        break
                await asyncio.wait_for(task, timeout=5)
            finally:
                lane_lines.extend(app._active_lane().lines)
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    with capsys.disabled():
        asyncio.run(scenario())

    content = (root / "app.py").read_text(encoding="utf-8")
    if expected == "asks":
        assert screens, "Classic must show the diff before writing"
        assert content == "value = 2\n"
        assert len(calls) == 2
    elif expected == "quiet":
        assert not screens, "Flow must not ask for recoverable local work"
        assert content == "value = 2\n"
        assert len(calls) == 2
    else:
        assert not screens
        assert content == "value = 1\n"
        assert calls == []
        assert seen_tools == []
        assert any("Provider request DENY" in line[1] for line in lane_lines), lane_lines


def test_a_local_provider_answers_through_the_real_tui_transport(tmp_path, monkeypatch, capsys):
    """The matrix provider row: one local model, the real HTTP/SSE transport.

    The fake provider in the other TUI tests replaces ``provider_complete``.
    This one keeps it real and points Ollama's preset at a loopback SSE server,
    so the TUI, the authority, egress and the wire protocol all participate.
    """
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("ISYCODE_PROVIDER", "ollama")
    monkeypatch.setenv("ISYCODE_MODEL", "local-fixture")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("isycode.egress._ips", lambda _host, _port: ("127.0.0.1",))
    received = []
    lane_lines = []

    async def scenario():
        async def server_handler(reader, writer):
            headers = await reader.readuntil(b"\r\n\r\n")
            content_length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                                  if line.lower().startswith(b"content-length:"))
            received.append(json.loads(await reader.readexactly(content_length)))
            body = (b'data: {"choices":[{"delta":{"content":"Local OK"}}]}\n\n'
                    b"data: [DONE]\n\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(server_handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{port}")
        async with server:
            app = TUIApp()
            startup = app._startup_workspace

            async def no_startup():
                return None

            app._startup_workspace = no_startup
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app._startup_workspace = startup
                task = asyncio.create_task(app._run_chat("Say OK."))
                try:
                    await asyncio.wait_for(task, timeout=10)
                finally:
                    lane_lines.extend(app._active_lane().lines)
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

    with capsys.disabled():
        asyncio.run(scenario())

    assert received, "the app never reached the local provider"
    assert any("Local OK" in line[1] for line in lane_lines), lane_lines
