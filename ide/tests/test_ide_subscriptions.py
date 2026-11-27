"""Subscription profiles must not inherit API billing or native host tools."""
import asyncio
import json
from pathlib import Path

import pytest

from core.subscriptions import SubscriptionService, SubscriptionError
from core.agent.providers.base import ProviderConfig
from core.agent.providers.subscription import SubscriptionProvider


def test_subscription_profile_pins_cli_and_private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_IDE_HOME", str(tmp_path / "private"))
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\necho 'codex-cli fixture'\n")
    executable.chmod(0o755)
    service = SubscriptionService()
    profile = service.configure("codex-subscription", str(executable))
    assert Path(profile["home"]).is_relative_to(tmp_path / "private")
    executable.write_text("#!/bin/sh\necho 'changed'\n")
    with pytest.raises(SubscriptionError, match="cambió"):
        service.identity("codex-subscription")


def test_claude_command_disables_native_tools_and_api_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_IDE_HOME", str(tmp_path / "private"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-inherited")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://unwanted.invalid")
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\necho 'fixture'\n")
    executable.chmod(0o755)
    service = SubscriptionService()
    identity = service.configure("claude-subscription", str(executable))
    argv = service.claude_command(identity, "sonnet", {"type": "object"})
    assert argv[argv.index("--tools") + 1] == ""
    assert "--restricted" in argv and "--safe-mode" in argv
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    env = service.environment(identity)
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_BASE_URL" not in env
    assert env["CLAUDE_CONFIG_DIR"] == identity["home"]


def test_codex_dynamic_tool_returns_to_host_before_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_IDE_HOME", str(tmp_path / "private"))
    service = SubscriptionService()
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\necho 'fixture'\n")
    executable.chmod(0o755)
    service.configure("codex-subscription", str(executable))
    closed = []
    class Connector:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): closed.append(True)
        async def complete(self, model, messages, tools, on_chunk=None):
            assert tools[0]["function"]["name"] == "write"
            return {"text": "review this", "tool_calls": [{"id": "provider-id", "function": {"name": "write", "arguments": '{"path":"a.py","content":"proposal"}'}}]}
    monkeypatch.setattr("core.agent.providers.subscription.CodexConnector", Connector)
    async def run():
        config = ProviderConfig("subscription", "codex-subscription", "auto", "https://chatgpt.com/backend-api/codex", auth="subscription")
        provider = SubscriptionProvider(config, None)
        try:
            response = await provider.complete([{"role": "user", "content": "modify"}], [{"type": "function", "function": {"name": "write", "parameters": {"type": "object"}}}])
            assert response.tool_calls[0].arguments == {"path": "a.py", "content": "proposal"}
            assert not (tmp_path / "a.py").exists()
            assert closed == [True]
        finally:
            await provider.close()
    asyncio.run(run())


def test_official_cli_size_and_private_http_routing(tmp_path, monkeypatch):
    from core.connectors.codex import CodexConnector
    import tomllib
    home = tmp_path / "codex-private"
    peer = CodexConnector("/usr/bin/true", home)
    peer._prepare_home()
    config = tomllib.loads((home / "config.toml").read_text())
    assert config["model_provider"] == "openai_http"
    assert config["model_providers"]["openai_http"]["supports_websockets"] is False
    # Installed Codex is currently larger than 256 MB. Header-only sparse fixture.
    executable = tmp_path / "large-cli"
    with executable.open("wb") as stream:
        stream.truncate(294_410_952)
    executable.chmod(0o755)
    assert SubscriptionService().configure("codex-subscription", str(executable))["sha256"]


def test_expired_grok_session_does_not_fallback_to_api(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "fixture-must-not-be-used")
    executable = tmp_path / "grok"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    service = SubscriptionService()
    identity = service.configure("grok-subscription", str(executable))
    auth = Path(identity["home"]) / ".grok" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps({"session": {"oidc_issuer": "https://auth.x.ai", "key": "expired-fixture", "expires_at": "2000-01-01T00:00:00Z"}}))
    auth.chmod(0o600)
    assert service.grok_token(identity) == ""
    async def run():
        provider = SubscriptionProvider(ProviderConfig("grok", "grok-subscription", "fixture-model", "https://cli-chat-proxy.grok.com/v1", auth="subscription"), None)
        try:
            with pytest.raises(SubscriptionError, match="expirada"):
                await anext(provider.stream_completion([{"role": "user", "content": "test"}]))
        finally:
            await provider.close()
    asyncio.run(run())
