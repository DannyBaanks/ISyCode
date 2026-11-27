"""Test the Claude Code provider (headless) with a fake `claude` binary.

Verifies:
- ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL injection
- stream-json parsing (text deltas, tool markers, final result)
- json (non-stream) parsing
"""

import asyncio
import pytest
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.secret_broker import SecretBroker
from core.agent.providers.registry import ProviderRegistry, DEFAULT_ENDPOINTS


FAKE_SCRIPT = r'''@echo off
setlocal
echo %ANTHROPIC_BASE_URL%> "%FAKE_LOGFILE%"
echo %ANTHROPIC_API_KEY%>> "%FAKE_LOGFILE%"
echo %ANTHROPIC_AUTH_TOKEN%>> "%FAKE_LOGFILE%"
echo %ANTHROPIC_MODEL%>> "%FAKE_LOGFILE%"
python "%~dp0fake_claude_logic.py" %*
'''

FAKE_LOGIC_STREAM = r'''
import json, sys

streaming = False
for a in sys.argv:
    if "stream" in a:
        streaming = True
        break
if streaming:
    events = [
        {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Read"}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "Done from Claude Code"},
    ]
else:
    events = [
        {"type": "result", "subtype": "success", "is_error": False, "result": "Final answer from fake claude"}
    ]
for e in events:
    print(json.dumps(e), flush=True)
'''


def setup_fake_claude(tmp: Path) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "fake_claude_logic.py").write_text(FAKE_LOGIC_STREAM, encoding="utf-8")
    logfile = tmp / "env_log.txt"
    script = FAKE_SCRIPT.replace("%FAKE_LOGFILE%", str(logfile))
    (bin_dir / "claude.cmd").write_text(script, encoding="utf-8")
    return bin_dir, logfile


async def _test_direct_anthropic(tmp: Path):
    print("=== Claude Code: direct Anthropic key ===")
    bin_dir, logfile = setup_fake_claude(tmp)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    broker = SecretBroker()
    broker.set("claude", "sk-ant-test-000")
    registry = ProviderRegistry(broker, config_path=tmp / "config.yaml")
    registry.add("claude", "claude", "sonnet")
    provider = registry.get("claude")

    resp = await provider.complete(
        [{"role": "system", "content": "You are ISYCO."},
         {"role": "user", "content": "test"}]
    )
    assert resp.content == "Final answer from fake claude", resp
    assert resp.finish_reason == "stop"

    lines = logfile.read_text(encoding="utf-8", errors="replace").splitlines()
    # line0: base url (empty for direct), line1: api key, line2: auth token, line3: model
    assert lines[1] == "sk-ant-test-000", f"API key not injected: {lines}"
    assert lines[2].startswith("ECHO"), f"AUTH_TOKEN should be empty for direct: {lines}"
    print(f"  ANTHROPIC_API_KEY injected: {lines[1]}")
    print(f"  {resp.content!r}")
    print("  OK")


async def _test_routed_nvidia(tmp: Path):
    print("\n=== Claude Code: routed via NVIDIA Anthropic endpoint ===")
    bin_dir, logfile = setup_fake_claude(tmp)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    broker = SecretBroker()
    broker.set("nvidia-claude", "nvapi-test-123")
    registry = ProviderRegistry(broker, config_path=tmp / "config.yaml")
    registry.add(
        "nvidia-claude", "claude", "meta/llama-3.3-70b-instruct",
        endpoint="https://integrate.api.nvidia.com/anthropic"
    )
    provider = registry.get("nvidia-claude")

    resp = await provider.complete([{"role": "user", "content": "hi"}])
    lines = logfile.read_text(encoding="utf-8", errors="replace").splitlines()
    assert lines[0] == "https://integrate.api.nvidia.com/anthropic", f"BASE_URL: {lines}"
    assert lines[1].startswith("ECHO"), f"API_KEY should be empty when routed: {lines}"
    assert lines[2] == "nvapi-test-123", f"AUTH_TOKEN not injected: {lines}"
    assert lines[3] == "meta/llama-3.3-70b-instruct"
    print(f"  ANTHROPIC_BASE_URL: {lines[0]}")
    print(f"  ANTHROPIC_AUTH_TOKEN: {lines[2]}")
    print(f"  ANTHROPIC_MODEL: {lines[3]}")
    print(f"  {resp.content!r}")
    print("  OK")


async def _test_stream(tmp: Path):
    print("\n=== Claude Code: stream-json parsing ===")
    bin_dir, _ = setup_fake_claude(tmp)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    broker = SecretBroker()
    broker.set("claude", "sk-ant-test-000")
    registry = ProviderRegistry(broker, config_path=tmp / "config.yaml")
    registry.add("claude", "claude", "sonnet")
    provider = registry.get("claude")

    chunks = []
    async for chunk in provider.stream(
        [{"role": "user", "content": "stream test"}]
    ):
        chunks.append(chunk)

    text = "".join(chunks)
    assert "Hello world" in text, f"stream text missing: {text!r}"
    assert "[TOOL] Read" in text, f"tool marker missing: {text!r}"
    assert "Done from Claude Code" in text
    print(f"  Stream: {text!r}")
    print("  OK")


async def main():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        await _test_direct_anthropic(tmp)
        await _test_routed_nvidia(tmp)
        await _test_stream(tmp)
        # Cleanup test keys
        SecretBroker().remove("claude")
        SecretBroker().remove("nvidia-claude")
    print("\nALL CLAUDE CODE PROVIDER TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())


def test_direct_anthropic(tmp_path):
    registry = ProviderRegistry(SecretBroker(), config_path=tmp_path / "config.yaml")
    registry.add("legacy", "claude", "sonnet")
    with pytest.raises(ValueError, match="restringido"):
        registry.get("legacy")


def test_routed_nvidia(tmp_path):
    registry = ProviderRegistry(SecretBroker(), config_path=tmp_path / "config.yaml")
    registry.add("legacy", "claude", "sonnet", endpoint="https://integrate.api.nvidia.com/anthropic")
    with pytest.raises(ValueError, match="restringido"):
        registry.get("legacy")


def test_stream(tmp_path):
    from core.agent.providers.subscription import SubscriptionProvider
    registry = ProviderRegistry(SecretBroker(), config_path=tmp_path / "config.yaml")
    registry.add("private", "claude-subscription", "sonnet", auth="subscription")
    async def check():
        provider = registry.get("private")
        assert isinstance(provider, SubscriptionProvider)
        await provider.close()
    asyncio.run(check())
