"""Local stdio MCP servers: user config only, grant + approval to start and to call."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.mcp_local import (
    LocalMCPOwner, MCPSession, PLAYWRIGHT_COMMAND, ServerConfig, function_name,
    load_config, visible_tools,
)
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")

FAKE_SERVER = r'''
import json, os, sys
def send(message):
    sys.stdout.write(json.dumps(message) + "\n"); sys.stdout.flush()
print("server log noise on stdout", flush=True)
for line in sys.stdin:
    message = json.loads(line)
    method, mid = message.get("method"), message.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2025-06-18",
              "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": 900, "method": "ping"})
        send({"jsonrpc": "2.0", "id": 901, "method": "roots/list"})
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": "echo", "description": "Echo text", "inputSchema": {
                "type": "object", "properties": {"text": {"type": "string"}}}},
            {"name": "bad name!", "description": "x"}]}})
    elif method == "tools/call":
        args = message["params"]["arguments"]
        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [
            {"type": "text", "text": "echo:" + args.get("text", "") + " cwd:" + os.getcwd()
             + " secret:" + os.environ.get("OPENAI_API_KEY", "none")}]}})
    elif mid is not None and method is None:
        pass
'''


@pytest.fixture
def mcp(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    script = tmp_path / "server.py"
    script.write_text(FAKE_SERVER)
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    approvals = ActionApprovalStore()
    configs = {"fake": ServerConfig("fake", (sys.executable, str(script)), (("MODE", "test"),))}
    return LocalMCPOwner(root, authority, approvals), authority, approvals, configs


def _grant(authority, executable, server="fake"):
    authority.set_grant("mcp.local.start", enabled=True, executables=[executable])
    authority.set_grant("mcp.local.invoke", enabled=True, targets=[server])


def test_config_is_validated(tmp_path):
    path = tmp_path / "mcp.json"
    assert load_config(path) == {}
    path.write_text(json.dumps({"servers": {"docs": {"command": ["npx", "docs-mcp"],
                                                     "env": {"TOKEN": "x"}}}}))
    path.chmod(0o600)
    assert load_config(path)["docs"].argv == ("npx", "docs-mcp")
    for bad in ({"servers": {"Bad Name": {"command": ["x"]}}},
                {"servers": {"ok": {"command": []}}},
                {"servers": {"ok": {"command": ["x"], "env": {"lower": "v"}}}},
                {"nope": {}}):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            load_config(path)
    path.write_text(json.dumps({"servers": {}}))
    path.chmod(0o666)
    with pytest.raises(ValueError, match="writable"):
        load_config(path)


def test_start_needs_grant_and_approval(mcp):
    owner, authority, approvals, configs = mcp
    preview = owner.prepare_start("fake", configs)
    assert asyncio.run(owner.start(preview, approvals.issue(preview.request))).decision == "DENY"
    _grant(authority, preview.request.parameters["executable"])
    assert asyncio.run(owner.start(preview, None)).decision == "DENY"
    assert owner.sessions == {}


def test_tools_are_listed_and_each_call_is_approved_and_journaled(mcp):
    owner, authority, approvals, configs = mcp

    async def scenario():
        preview = owner.prepare_start("fake", configs)
        _grant(authority, preview.request.parameters["executable"])
        started = await owner.start(preview, approvals.issue(preview.request))
        assert started.decision == "ALLOW", started.reason
        assert json.loads(started.text)["tools"] == ["echo"]
        tools = owner.chat_tools()
        assert [tool["function"]["name"] for tool in tools] == ["mcp__fake__echo"]
        assert "untrusted" in tools[0]["function"]["description"]
        assert owner.resolve_function("mcp__fake__echo") == ("fake", "echo")
        call = owner.prepare_call("fake", "echo", {"text": "hi"})
        assert (await owner.call(call, None)).decision == "DENY"
        result = await owner.call(call, approvals.issue(call.request))
        await owner.stop_all()
        return result

    result = asyncio.run(scenario())
    text = json.loads(result.text)["text"]
    assert result.decision == "ALLOW" and text.startswith("echo:hi")
    assert f"cwd:{owner.root}" in text and "secret:none" in text
    assert ActionAuditJournal(owner.root).verify().receipts == 2


def test_calls_to_unknown_tools_or_stopped_servers_are_refused(mcp):
    owner, authority, approvals, configs = mcp

    async def scenario():
        preview = owner.prepare_start("fake", configs)
        _grant(authority, preview.request.parameters["executable"])
        await owner.start(preview, approvals.issue(preview.request))
        with pytest.raises(ValueError):
            owner.prepare_call("fake", "bad name!", {})
        with pytest.raises(ValueError):
            owner.prepare_call("fake", "echo", ["not", "an", "object"])
        call = owner.prepare_call("fake", "echo", {"text": "x"})
        await owner.stop("fake")
        return await owner.call(call, approvals.issue(call.request))

    assert asyncio.run(scenario()).decision == "DENY"


def test_invoke_grant_is_per_server(mcp):
    owner, authority, approvals, configs = mcp

    async def scenario():
        preview = owner.prepare_start("fake", configs)
        _grant(authority, preview.request.parameters["executable"], server="other")
        await owner.start(preview, approvals.issue(preview.request))
        call = owner.prepare_call("fake", "echo", {"text": "x"})
        outcome = await owner.call(call, approvals.issue(call.request))
        await owner.stop_all()
        return outcome

    assert asyncio.run(scenario()).decision == "DENY"


@pytest.mark.parametrize("change", [
    {"executable": "relative/bin"}, {"cwd": "/tmp"}, {"env_keys": ("lower",)},
    {"argv": ()}, {"extra": 1},
])
def test_boundary_rejects_forged_start_requests(mcp, change):
    owner, authority, approvals, configs = mcp
    preview = owner.prepare_start("fake", configs)
    _grant(authority, preview.request.parameters["executable"])
    params = {**dict(preview.request.parameters), **change}
    request = ActionRequest("mcp.local.start", owner.root, "fake", params, execution_owner="mcp_local")
    gate = ProductActionGate(owner.root, authority, owner_id="mcp_local")
    _, decision = gate.authorize(request, approvals=approvals, approval=approvals.issue(request))
    assert not decision.allowed


def test_function_names_fit_provider_limits():
    assert function_name("s", "t") == "mcp__s__t"
    assert len(function_name("a" * 32, "b" * 64)) == 64


def test_playwright_preset_exposes_only_read_only_snapshot_tool():
    config = ServerConfig("playwright", PLAYWRIGHT_COMMAND)
    tools = [
        {"name": "browser_snapshot", "description": "read page", "inputSchema": {"type": "object"}},
        {"name": "browser_navigate", "description": "navigate", "inputSchema": {"type": "object"}},
        {"name": "browser_click", "description": "click", "inputSchema": {"type": "object"}},
        {"name": "browser_evaluate", "description": "run JS", "inputSchema": {"type": "object"}},
    ]

    assert [tool["name"] for tool in visible_tools(config, tools)] == ["browser_snapshot"]


def test_playwright_snapshot_is_filtered_before_it_reaches_chat(mcp):
    owner, authority, approvals, _ = mcp
    snapshot = '''- generic [active] [ref=e1]:
  - banner [ref=e2]:
    - navigation [ref=e3]:
      - link "Log in" [ref=e4] [cursor=pointer]
  - generic [ref=e5]:
    - heading "Hackathon title" [level=1] [ref=e6]
    - paragraph [ref=e7]: Deadline: 30 October.
  - contentinfo [ref=e8]:
    - link "Privacy" [ref=e9]
'''
    config = ServerConfig("playwright", PLAYWRIGHT_COMMAND)

    class RunningProcess:
        returncode = None

    session = MCPSession(config, RunningProcess(), tools=[{
        "name": "browser_snapshot", "description": "Read visible page text",
        "inputSchema": {"type": "object", "properties": {}},
    }])

    async def return_snapshot(method, params, timeout):
        assert method == "tools/call"
        assert params["name"] == "browser_snapshot"
        return {"content": [{"type": "text", "text": snapshot}], "isError": False}

    session.request = return_snapshot
    owner.sessions["playwright"] = session
    authority.set_grant("mcp.local.invoke", enabled=True, targets=["playwright"])

    async def invoke():
        preview = owner.prepare_call("playwright", "browser_snapshot", {})
        return await owner.call(preview, approvals.issue(preview.request))

    outcome = asyncio.run(invoke())
    payload = json.loads(outcome.text)

    assert outcome.decision == "ALLOW"
    assert payload["content"] == "Hackathon title\nDeadline: 30 October."
    assert payload["filtered_chars"] < payload["input_chars"]
    assert payload["untrusted"] is True
    assert "Log in" not in outcome.text
    assert "ref=e" not in outcome.text
    assert ActionAuditJournal(owner.root).verify().status == "PASS"


def _tui_methods():
    import ast

    package = Path(__file__).resolve().parents[1] / "src" / "isycode"
    found = {}
    for path in (package / "tui.py", *sorted(package.glob("tui_app_*.py"))):
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "TUIApp" and not node.name.endswith("Mixin"):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found[item.name] = ast.get_source_segment(source, item)
    return found


def test_tui_asks_before_starting_and_before_every_call():
    methods = _tui_methods()
    start = methods["_start_local_mcp"]
    assert start.index("LocalMCPConfirmScreen(") < start.index("mcp_owner.start(preview, approval)")
    call = methods["_call_local_mcp"]
    assert call.index("LocalMCPConfirmScreen(") < call.index("mcp_owner.call(preview")
    assert call.index("BrowserReadPreviewScreen(") < call.index("return outcome.text")
    assert "rejected_by_user" in call
    assert "stop_all()" in methods["on_unmount"]


@pytest.mark.parametrize("share", [False, True])
def test_browser_text_is_shown_before_it_can_reach_the_model(tmp_path, monkeypatch, share):
    from types import SimpleNamespace
    from test_daily_tui import configure
    from isycode.security import ActionRequest
    from isycode.tui import BrowserReadPreviewScreen, LocalMCPConfirmScreen, TUIApp

    root = configure(tmp_path, monkeypatch)
    request = ActionRequest("mcp.local.invoke", root, "playwright",
                            {"tool": "browser_snapshot"}, execution_owner="mcp_local")
    preview = SimpleNamespace(request=request, arguments={})
    body = "Approved visible page text"
    outcome = SimpleNamespace(
        decision="ALLOW", receipt=SimpleNamespace(receipt_id="rcpt_test"),
        text=json.dumps({"browser_read": True, "content": body, "input_chars": 80,
                         "filtered_chars": len(body), "truncated": False,
                         "untrusted": True}),
    )

    class FakeMCPOwner:
        def resolve_function(self, function):
            return ("playwright", "browser_snapshot")

        def prepare_call(self, server, tool, arguments):
            return preview

        async def call(self, preview, approval):
            return outcome

    async def scenario():
        app = TUIApp()
        app._local_mcp_owner = lambda: FakeMCPOwner()
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._call_local_mcp("mcp__playwright__browser_snapshot", {}))
            await pilot.pause()
            assert isinstance(app.screen, LocalMCPConfirmScreen)
            await pilot.click("#local-mcp-approve")
            await pilot.pause()
            assert isinstance(app.screen, BrowserReadPreviewScreen)
            assert body in str(app.screen.query_one("#browser-read-content Static").render())
            assert "not automatically certified" in str(
                app.screen.query_one("#browser-read-warning").render()).lower()
            await pilot.click("#browser-read-share" if share else "#browser-read-discard")
            result = await task
            if share:
                assert json.loads(result)["content"] == body
            else:
                assert json.loads(result) == {
                    "status": "rejected_by_user", "content_shared": False}

    asyncio.run(scenario())


def test_mcp_confirm_screen_cancels_by_default():
    from textual.app import App
    from isycode.tui import LocalMCPConfirmScreen

    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(LocalMCPConfirmScreen("t", "b", "{}", "Call once"), results.append)

    async def scenario(action):
        async with Host().run_test() as pilot:
            await pilot.pause()
            await action(pilot)
            await pilot.pause()

    asyncio.run(scenario(lambda pilot: pilot.press("escape")))
    asyncio.run(scenario(lambda pilot: pilot.press("enter")))
    asyncio.run(scenario(lambda pilot: pilot.click("#local-mcp-approve")))
    assert results == [False, False, True]
