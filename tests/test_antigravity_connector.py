"""Security, isolation, quota, and TUI tests for the Antigravity OAuth provider.

Verifies the three mandatory acceptance properties:
1. OAuth credentials stay exclusively inside official ``agy`` private storage;
   ISyCode never reads, copies, logs, or writes OAuth URLs/tokens to disk.
2. No built-in ``agy`` tool can bypass IsySentinel (hardened settings.json,
   PreToolUse deny-all hook, schema-only MCP, fail-closed permission/tool_call
   abort).
3. Data minimization (ephemeral artifacts purged on close, no prompts/secrets/
   images in audit logs) and explicit authorization for inline images through
   ProviderNetworkOwner.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import ProviderAuthSystembility, ProviderNetworkOwner
from isycode.antigravity_connector import (
    ANTIGRAVITY_ENDPOINT,
    AntigravityConnector,
    AntigravityConnectorError,
    _DENY_ALL_HOOK_SCRIPT,
    _SCHEMA_ONLY_MCP_SCRIPT,
    _auth_url,
    fetch_antigravity_quota,
    format_quota_line,
    parse_antigravity_usage,
)
from isycode.approvals import ActionApprovalStore
from isycode.provider_auth import (
    ANTIGRAVITY_AUTH_HOSTS,
    ProviderAuthOwner,
    antigravity_identity,
    auth_methods,
)
from isycode.provider_auth_screens import SubscriptionLoginScreen, _approved_login_url
from isycode.providers import PRESETS, Provider
from isycode.workspace_authority import WorkspaceAuthority


def _make_fake_agy(tmp_path: Path, mode: str = "ok") -> Path:
    script = tmp_path / f"fake_agy_{mode}.py"
    # Never put a path containing spaces (e.g. "ISyCo Git") into a POSIX shebang.
    py_shebang = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "/usr/bin/env python3"
    script.write_text(f"#!{py_shebang}\nMODE = {mode!r}\n{_FAKE_ACP_COMMON}\n", encoding="utf-8")
    script.chmod(0o700)
    return script


_FAKE_ACP_COMMON = """
import json, os, sys
mode = MODE
if len(sys.argv) >= 3 and sys.argv[1] == "-p" and sys.argv[2] == "/usage":
    slash_disabled = "--disable-slash-commands" in sys.argv
    if not slash_disabled:
        settings_path = os.path.join(os.environ.get("HOME", ""), ".gemini", "antigravity-cli", "settings.json")
        if os.path.isfile(settings_path):
            with open(settings_path, encoding="utf-8") as fh:
                slash_disabled = bool(json.load(fh).get("disableSlashCommands", False))
        if "--settings" in sys.argv:
            idx = sys.argv.index("--settings")
            if idx + 1 < len(sys.argv):
                override = json.loads(sys.argv[idx + 1])
                if "disableSlashCommands" in override:
                    slash_disabled = bool(override["disableSlashCommands"])
    if slash_disabled:
        sys.stdout.write(json.dumps({"status": "SUCCESS", "response": "/usage was passed through as a regular prompt"}) + "\\n")
        sys.stdout.flush()
        sys.exit(0)
    payload = {
        "status": "SUCCESS",
        "command": {
            "name": "usage",
            "data": {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "buckets": [
                            {"id": "gemini-5h", "name": "Five Hour Limit Remaining", "window": "5h",
                             "remaining_fraction": 0.91, "reset_time": "2026-11-25T04:00:00Z"},
                            {"id": "gemini-weekly", "name": "Weekly Limit Remaining", "window": "weekly",
                             "remaining_fraction": 0.64, "reset_time": "2026-11-30T20:00:00Z"},
                        ],
                    },
                    {
                        "name": "Claude and GPT models",
                        "buckets": [
                            {"id": "3p-5h", "name": "Five Hour Limit Remaining", "window": "5h",
                             "remaining_fraction": 1.0, "reset_time": "1970-01-01T00:00:00Z"},
                            {"id": "3p-weekly", "name": "Weekly Limit Remaining", "window": "weekly",
                             "remaining_fraction": 0.85, "reset_time": "2026-11-29T12:00:00Z"},
                        ],
                    },
                ]
            },
        },
    }
    sys.stdout.write(json.dumps(payload) + "\\n")
    sys.stdout.flush()
    sys.exit(0)

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    msg = json.loads(line)
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": 1,
            "agentCapabilities": {"promptCapabilities": {"image": True}, "auth": {"logout": {}}},
            "agentInfo": {"name": "Fake Antigravity ACP", "version": "1.0.0"},
        }})
    elif method == "authenticate":
        if mode == "login_url":
            browser = os.environ.get("BROWSER", "")
            if browser:
                import subprocess
                subprocess.run([browser, "https://accounts.google.com/o/oauth2/auth?state=SECRET_STATE_42"], check=False)
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mode == "bad_url":
            browser = os.environ.get("BROWSER", "")
            if browser:
                import subprocess
                subprocess.run([browser, "https://evil.example/oauth?state=1"], check=False)
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "auth/logout":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "session/new":
        if mode == "secret_error":
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": "LEAK_SECRET_TOKEN_XYZ"}})
            continue
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "sessionId": "sess-1",
            "models": {
                "currentModelId": "gemini-4-neon-high",
                "availableModels": [
                    {"modelId": "gemini-4-neon-high", "name": "Gemini 4 Neon (High)"},
                    {"modelId": "gemini-3.8-flash-low", "name": "Gemini 3.8 Flash (Low)"},
                    {"modelId": "claude-opus-5-5-high", "name": "Claude Opus 5.5 (High)"},
                ],
            },
            "_meta": {"antigravity": {"tier": {"name": "Google AI Pro", "id": "g1-pro-tier"}}},
        }})
    elif method == "session/set_model":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "session/close":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "session/prompt":
        if mode == "permission_rpc":
            send({"jsonrpc": "2.0", "id": 99, "method": "session/request_permission", "params": {"sessionId": "sess-1"}})
            continue
        if mode == "builtin_tool":
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "tool_call", "toolCallId": "c1", "name": "search_web", "args": {"query": "x"}},
            }})
            continue
        if mode == "undeclared_mcp":
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "tool_call", "toolCallId": "c1", "name": "mcp_isycode_not_declared", "args": {}},
            }})
            continue
        if mode == "isycode_tool":
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "usage_update", "used": 4321, "size": 1048576},
            }})
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Checking file."}},
            }})
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": "sess-1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call_123",
                    "name": "mcp_isycode_workspace_read",
                    "args": {"path": "README.md", "toolSummary": "Read README"},
                },
            }})
            continue
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "sess-1",
            "update": {"sessionUpdate": "usage_update", "used": 100, "size": 1048576},
        }})
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "sess-1",
            "update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "thinking"}},
        }})
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "sess-1",
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "PONG"}},
        }})
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "stopReason": "end_turn",
            "usage": {"inputTokens": 42, "outputTokens": 7, "cachedReadTokens": 10, "cachedWriteTokens": 0},
        }})
"""


# ── Requirement 1: OAuth isolation & zero token extraction/persistence ──

def test_auth_methods_and_preset_expose_antigravity_without_api_key():
    assert PRESETS["antigravity"]["api"] == "antigravity"
    assert PRESETS["antigravity"]["key_required"] is False
    assert [m["id"] for m in auth_methods("antigravity")] == ["browser"]


def test_oauth_url_validation_accepts_only_accounts_google_com():
    assert _auth_url("https://accounts.google.com/o/oauth2/auth?x=1").startswith("https://accounts.google.com/")
    assert _approved_login_url("https://accounts.google.com/o/oauth2/auth", allowed_hosts=("accounts.google.com",))
    for bad in (
        "http://accounts.google.com/o/oauth2/auth",
        "https://evil.example/o/oauth2/auth",
        "https://user@accounts.google.com/o/oauth2/auth",
        "https://accounts.google.com:8443/o/oauth2/auth",
        "https://accounts.google.com/a b",
    ):
        with pytest.raises(AntigravityConnectorError):
            _auth_url(bad)
        assert _approved_login_url(bad, allowed_hosts=("accounts.google.com",)) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_oauth_url_captured_only_in_memory_and_never_written_to_disk(tmp_path):
    fake_agy = _make_fake_agy(tmp_path, "login_url")
    home = tmp_path / "managed-home"

    async def scenario():
        async with AntigravityConnector(str(fake_agy), home, timeout_s=10, allow_browser_capture=True) as conn:
            challenge = await conn.start_login("browser")
            assert challenge["url"] == "https://accounts.google.com/o/oauth2/auth?state=SECRET_STATE_42"
            assert await conn.wait_login(challenge["login_id"]) is True
            # Verify no file inside managed home contains the OAuth URL or state token.
            for item in home.rglob("*"):
                if item.is_file():
                    assert "SECRET_STATE_42" not in item.read_text(encoding="utf-8", errors="ignore")

    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="POSIX chmod 000 verification")
def test_connector_never_reads_or_copies_private_auth_files(tmp_path):
    fake_agy = _make_fake_agy(tmp_path, "ok")
    home = tmp_path / "managed-home"
    auth_dir = home / ".config" / "antigravity"
    auth_dir.mkdir(parents=True)
    secret_file = auth_dir / "private_oauth_token.json"
    secret_file.write_text('{"refresh_token": "DO_NOT_READ_ME"}\n', encoding="utf-8")
    secret_file.chmod(0o000)

    try:
        async def scenario():
            async with AntigravityConnector(str(fake_agy), home, timeout_s=10) as conn:
                acct = await conn.account()
                assert acct == {"authenticated": True, "method": "antigravity", "plan": "Google AI Pro"}
                models = await conn.models()
                assert "gemini-4-neon-high" in models
                assert "claude-opus-5-5-high" in models
        asyncio.run(scenario())
        assert secret_file.exists()
    finally:
        secret_file.chmod(0o600)


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_connector_errors_never_leak_peer_diagnostics_or_secrets(tmp_path):
    fake_agy = _make_fake_agy(tmp_path, "secret_error")
    home = tmp_path / "managed-home"

    async def scenario():
        async with AntigravityConnector(str(fake_agy), home, timeout_s=10) as conn:
            with pytest.raises(AntigravityConnectorError) as exc_info:
                await conn.models()
            assert "LEAK_SECRET_TOKEN_XYZ" not in str(exc_info.value)

    asyncio.run(scenario())


# ── Requirement 2: Built-in tool isolation (no IsySentinel bypass) ─────

def test_prepare_home_writes_hardened_settings_and_deny_all_hook(tmp_path):
    fake_agy = _make_fake_agy(tmp_path, "ok")
    home = tmp_path / "managed-home"
    conn = AntigravityConnector(str(fake_agy), home, timeout_s=10)
    conn._prepare_home()

    settings = json.loads((home / ".gemini" / "antigravity-cli" / "settings.json").read_text(encoding="utf-8"))
    assert settings["toolPermission"] == "strict"
    assert settings["allowNonWorkspaceAccess"] is False
    assert settings["enableTerminalSandbox"] is True
    assert settings["historySize"] == 0
    for rule in ("read_file(*)", "write_file(*)", "command(*)", "unsandboxed(*)",
                 "read_url(*)", "execute_url(*)", "download_url(*)"):
        assert rule in settings["permissions"]["deny"]

    hooks_file = home / "sandbox-cwd" / ".agents" / "hooks.json"
    hooks = json.loads(hooks_file.read_text(encoding="utf-8"))
    pre = hooks["isycode-sentinel-wall"]["PreToolUse"][0]
    assert pre["matcher"] == "*"

    hook_script = home / "sandbox-cwd" / ".agents" / "deny_all_hook.py"
    for tool_name in ("read_file", "run_command", "search_web", "write_file", "mcp_isycode_x"):
        proc = subprocess.run(
            [sys.executable, str(hook_script)],
            input=json.dumps({"hookEventName": "PreToolUse", "toolCall": {"id": "1", "name": tool_name, "args": {}}}),
            capture_output=True, text=True, check=True,
        )
        decision = json.loads(proc.stdout)
        assert decision["decision"] == "deny"


def test_schema_only_mcp_server_advertises_tools_and_always_denies_execution(tmp_path):
    tools_file = tmp_path / "tools.json"
    tools_file.write_text(json.dumps([
        {"name": "workspace_read", "description": "Read", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}}
    ]), encoding="utf-8")
    server_file = tmp_path / "mcp.py"
    server_file.write_text(_SCHEMA_ONLY_MCP_SCRIPT, encoding="utf-8")

    requests = "\n".join(json.dumps(m) for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "workspace_read", "arguments": {"path": "x"}}},
    )) + "\n"
    proc = subprocess.run([sys.executable, str(server_file), str(tools_file)],
                          input=requests, capture_output=True, text=True, check=True)
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert responses[1]["result"]["tools"][0]["name"] == "workspace_read"
    assert "error" in responses[2] and responses[2]["error"]["code"] == -32000


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
@pytest.mark.parametrize("bad_mode", ["permission_rpc", "builtin_tool", "undeclared_mcp"])
def test_builtin_tool_or_permission_request_aborts_fail_closed(tmp_path, bad_mode):
    fake_agy = _make_fake_agy(tmp_path, bad_mode)
    home = tmp_path / "managed-home"

    async def scenario():
        async with AntigravityConnector(str(fake_agy), home, timeout_s=10) as conn:
            with pytest.raises(AntigravityConnectorError):
                await conn.complete("gemini-4-neon-high", [{"role": "user", "content": "hi"}])

    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_declared_isycode_tool_is_captured_and_returned_to_sentinel(tmp_path):
    fake_agy = _make_fake_agy(tmp_path, "isycode_tool")
    home = tmp_path / "managed-home"
    tools = [{
        "type": "function",
        "function": {
            "name": "workspace_read",
            "description": "Read a workspace file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    }]

    async def scenario():
        chunks = []
        async with AntigravityConnector(str(fake_agy), home, timeout_s=10) as conn:
            result = await conn.complete(
                "gemini-4-neon-high",
                [{"role": "user", "content": "Read README.md"}],
                tools=tools,
                on_chunk=lambda kind, text: chunks.append((kind, text)),
            )
            assert result["text"] == "Checking file."
            assert result["usage"] == {"input_tokens": 4321}
            assert len(result["tool_calls"]) == 1
            call = result["tool_calls"][0]
            assert call["id"] == "call_123"
            assert call["function"]["name"] == "workspace_read"
            # Synthetic toolSummary stripped because schema did not declare it.
            assert json.loads(call["function"]["arguments"]) == {"path": "README.md"}
            assert conn._closed is True

    asyncio.run(scenario())


# ── Requirement 3: Data minimization & image authorization ─────────────

@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_ephemeral_conversation_artifacts_purged_on_close_while_auth_kept(tmp_path):
    fake_agy = _make_fake_agy(tmp_path, "ok")
    home = tmp_path / "managed-home"

    auth_file = home / ".config" / "antigravity" / "oauth_state"
    auth_file.parent.mkdir(parents=True)
    auth_file.write_text("official-client-private-state", encoding="utf-8")

    async def scenario():
        async with AntigravityConnector(str(fake_agy), home, timeout_s=10) as conn:
            # Simulate transient files written by agy during a turn.
            app_data = home / ".gemini" / "antigravity-cli"
            (app_data / "conversations").mkdir(parents=True, exist_ok=True)
            (app_data / "conversations" / "c1.pb").write_bytes(b"SENSITIVE_PROMPT_BYTES")
            (app_data / "brain" / "c1").mkdir(parents=True, exist_ok=True)
            (app_data / "brain" / "c1" / "notes.md").write_text("SECRET_NOTES", encoding="utf-8")
            (app_data / "cli.log").write_text("SECRET_LOG", encoding="utf-8")
            (app_data / "history.jsonl").write_text("SECRET_PROMPT", encoding="utf-8")

            chunks = []
            res = await conn.complete(
                "gemini-3.8-flash-low",
                [{"role": "user", "content": "ping"}],
                on_chunk=lambda k, t: chunks.append((k, t)),
            )
            assert res["text"] == "PONG"
            assert res["usage"] == {
                "input_tokens": 42, "output_tokens": 7,
                "cache_read_input_tokens": 10, "cache_creation_input_tokens": 0,
            }
            assert ("reasoning", "thinking") in chunks
            assert ("content", "PONG") in chunks

        app_data = home / ".gemini" / "antigravity-cli"
        assert not (app_data / "conversations").exists()
        assert not (app_data / "brain").exists()
        assert not (app_data / "cli.log").exists()
        assert not (app_data / "history.jsonl").exists()
        assert auth_file.exists() and auth_file.read_text(encoding="utf-8") == "official-client-private-state"

    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_images_require_inline_data_uri_and_provider_network_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    fake_agy = _make_fake_agy(tmp_path, "ok")
    monkeypatch.setenv("ISYCODE_AGY_EXECUTABLE", str(fake_agy))
    monkeypatch.setattr("isycode.egress._ips", lambda host, port: ["93.184.216.34"])

    # Reject non-inline / local-path image URLs inside connector.
    async def reject_bad_image():
        home = tmp_path / "state" / "accounts" / "antigravity"
        async with AntigravityConnector(str(fake_agy), home, timeout_s=10) as conn:
            for bad_url in ("file:///etc/passwd", "/tmp/secret.png", "https://remote.example/x.png"):
                with pytest.raises(AntigravityConnectorError):
                    await conn.complete(
                        "gemini-4-neon-high",
                        [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": bad_url}}]}],
                    )
    asyncio.run(reject_bad_image())

    # Sending an inline image must pass ProviderNetworkOwner grant and never log prompt/image bytes.
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root)
    provider = Provider(name="antigravity", model="gemini-4-neon-high")
    owner = ProviderNetworkOwner(root, authority)
    image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+p6d0AAAAASUVORK5CYII="
    secret_prompt = "CONFIDENTIAL_PROMPT_TEXT_999"
    material = {
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": secret_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]}]
    }

    async def gated_send():
        # Denied without explicit provider.request host grant.
        sent = []
        resp, outcome = await owner.execute(provider, material, lambda: (sent.append(True) or asyncio.sleep(0)))
        assert outcome.decision == "DENY" and resp is None and not sent

        # Allowed only after explicit host grant; audit log must never contain prompt or image bytes.
        authority.set_grant("provider.request", enabled=True, network_hosts=list(ANTIGRAVITY_AUTH_HOSTS))
        async def do_send():
            async with AntigravityConnector(str(fake_agy), Path(provider.connector_identity["home"]), timeout_s=10) as conn:
                return await conn.complete(provider.model, material["messages"])
        resp, outcome = await owner.execute(provider, material, do_send)
        assert outcome.decision == "ALLOW" and resp["text"] == "PONG"

    asyncio.run(gated_send())
    journal_dir = root.parent / "state"
    # Verify ActionAuditJournal passes and stores no raw prompt or base64 image payload.
    journal = ActionAuditJournal(root)
    assert journal.verify().status == "PASS"
    for p in journal.path.parent.rglob("*"):
        if p.is_file():
            raw = p.read_text(encoding="utf-8", errors="ignore")
            assert secret_prompt not in raw
            assert image_b64 not in raw


# ── Auth owner, Sentinel boundary, and 5h/weekly quota ─────────────────

@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_antigravity_auth_owner_requires_grant_approval_and_verifies_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "project"
    root.mkdir()
    fake_agy = _make_fake_agy(tmp_path, "ok")
    authority = WorkspaceAuthority(root)
    approvals = ActionApprovalStore()

    class FakePeer:
        def __init__(self, *args, **kwargs):
            self.closed = False
        async def __aenter__(self): return self
        async def start_login(self, method):
            return {"method": method, "login_id": "agy_1", "provider": "antigravity",
                    "url": "https://accounts.google.com/o/oauth2/auth?state=ok"}
        async def wait_login(self, login_id): return True
        async def account(self): return {"authenticated": True, "method": "antigravity", "plan": "Google AI Pro"}
        async def close(self): self.closed = True

    owner = ProviderAuthOwner(
        root, authority, approvals, executable=str(fake_agy),
        connector_factory=FakePeer, provider="antigravity",
    )
    req = owner.request("login", "browser")
    with pytest.raises(ValueError):
        owner.request("login", "device")

    async def scenario():
        assert (await owner.begin(req, None))[0].decision == "DENY"
        authority.set_grant("provider.authenticate", enabled=True, targets=["antigravity"],
                            executables=[str(fake_agy)], network_hosts=list(ANTIGRAVITY_AUTH_HOSTS))
        assert (await owner.begin(req, None))[0].decision == "DENY"
        outcome, challenge = await owner.begin(req, approvals.issue(req, ttl_seconds=30))
        assert outcome.decision == "ALLOW"
        assert challenge["provider"] == "antigravity"
        fin_outcome, account = await owner.finish()
        assert fin_outcome.decision == "ALLOW"
        assert account["plan"] == "Google AI Pro"
        assert ActionAuditJournal(root).verify().status == "PASS"

    asyncio.run(scenario())


def test_parse_antigravity_usage_5h_and_weekly_and_format_line():
    sample = json.dumps({
        "status": "SUCCESS",
        "command": {
            "name": "usage",
            "data": {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "buckets": [
                            {"id": "gemini-weekly", "name": "Weekly Limit Remaining", "window": "weekly",
                             "remaining_fraction": 0.577, "reset_time": "2026-11-30T20:00:00Z"},
                            {"id": "gemini-5h", "name": "Five Hour Limit Remaining", "window": "5h",
                             "remaining_fraction": 0.949, "reset_time": "2026-11-25T04:00:00Z"},
                        ],
                    },
                    {
                        "name": "Claude and GPT models",
                        "buckets": [
                            {"id": "3p-weekly", "name": "Weekly Limit Remaining", "window": "weekly",
                             "remaining_fraction": 1.0, "reset_time": "1970-01-01T00:00:00Z"},
                            {"id": "3p-5h", "name": "Five Hour Limit Remaining", "window": "5h",
                             "remaining_fraction": 0.80, "reset_time": "2026-11-25T02:30:00Z"},
                        ],
                    },
                ]
            },
        },
    })
    parsed = parse_antigravity_usage(sample)
    assert parsed["ok"] is True
    assert parsed["families"]["gemini"]["5h"]["pct"] == 94.9
    assert parsed["families"]["gemini"]["weekly"]["pct"] == 57.7
    assert parsed["families"]["claude_gpt"]["5h"]["pct"] == 80.0
    now = dt.datetime(2026, 11, 25, 0, 0, 0, tzinfo=dt.timezone.utc)
    assert format_quota_line(parsed, "gemini-4-neon-high", now=now) == "5h 95% (4h00m) · 7d 58% (5d20h)"
    assert format_quota_line(parsed, "claude-opus-5-5-high", now=now) == "5h 80% (2h30m) · 7d 100%"
    assert parse_antigravity_usage("not-json")["ok"] is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_fetch_antigravity_quota_runs_in_isolated_home(tmp_path):
    fake_agy = _make_fake_agy(tmp_path, "ok")
    home = tmp_path / "managed-home"
    quota = asyncio.run(fetch_antigravity_quota(str(fake_agy), home, timeout_s=10))
    assert quota["ok"] is True
    assert quota["families"]["gemini"]["5h"]["pct"] == 91.0
    assert quota["families"]["gemini"]["weekly"]["pct"] == 64.0
    assert not (home / ".gemini" / "antigravity-cli" / "cli.log").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_tui_antigravity_quota_requires_host_grant_and_renders_in_usage_panel(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    from isycode.providers import save_provider_selection
    from isycode.tui import TUIApp
    from textual.widgets import Static

    configure(tmp_path, monkeypatch)
    fake_agy = _make_fake_agy(tmp_path, "ok")
    monkeypatch.setenv("ISYCODE_AGY_EXECUTABLE", str(fake_agy))
    monkeypatch.setenv("ISYCODE_PROVIDER", "antigravity")
    monkeypatch.setenv("ISYCODE_MODEL", "gemini-4-neon-high")
    monkeypatch.setattr("isycode.egress._ips", lambda host, port: ["93.184.216.34"])
    save_provider_selection("antigravity", "gemini-4-neon-high")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            authority = WorkspaceAuthority(app._workspace_root)
            authority.set_mode("security")
            authority.set_grant("provider.request", enabled=False)
            # Without host grant, /quota is denied fail-closed.
            denied = await app._refresh_antigravity_quota(report=True)
            assert denied is None
            assert app._antigravity_quota is None

            # Grant Antigravity host and query 5h + weekly quota.
            authority.set_grant("provider.request", enabled=True, network_hosts=list(ANTIGRAVITY_AUTH_HOSTS))
            quota = await app._refresh_antigravity_quota(report=True)
            assert quota is not None and quota["ok"] is True
            await pilot.pause()
            status_text = app._usage_status_text()
            assert "5h 91%" in status_text and "7d 64%" in status_text
            rendered = str(app.query_one("#usage-status", Static).render())
            assert "5h 91%" in rendered

    with capsys.disabled():
        asyncio.run(scenario())
