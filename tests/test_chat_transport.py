from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isycode.chat_transport import assistant_turn, provider_complete, uses_anthropic


def test_uses_anthropic():
    provider_claude = MagicMock()
    provider_claude.name = "anthropic"
    assert uses_anthropic(provider_claude) is True

    provider_openai = MagicMock()
    provider_openai.name = "openai"
    assert uses_anthropic(provider_openai) is False

    provider_none = MagicMock()
    provider_none.name = "unknown_provider"
    assert uses_anthropic(provider_none) is False


def test_assistant_turn_simple_text():
    response = {"text": "Hello world!", "tool_calls": []}
    turn = assistant_turn(response)
    assert turn == {
        "role": "assistant",
        "content": "Hello world!",
        "tool_calls": [],
    }
    assert "_anthropic_content" not in turn


def test_assistant_turn_empty_text():
    response = {"text": "", "tool_calls": []}
    turn = assistant_turn(response)
    assert turn["content"] is None


def test_assistant_turn_with_tool_calls():
    calls = [{"id": "call_1", "type": "function", "function": {"name": "test"}}]
    response = {"text": "Executing...", "tool_calls": calls}
    turn = assistant_turn(response)
    assert turn["tool_calls"] == calls


def test_assistant_turn_with_anthropic_thinking():
    blocks = [{"type": "thinking", "thinking": "Let me reason..."}]
    response = {"text": "Final answer", "tool_calls": [], "anthropic_content": blocks}
    turn = assistant_turn(response)
    assert turn["_anthropic_content"] == blocks
    assert turn["content"] == "Final answer"


@pytest.mark.asyncio
async def test_provider_complete_anthropic():
    provider = MagicMock()
    provider.name = "anthropic"
    provider.api_key = "test_key"
    provider.model = "claude-3-5-sonnet"
    provider.reasoning_effort = "high"
    provider.base_url = "https://api.anthropic.com"

    mock_resp = {"text": "Anthropic response", "tool_calls": []}
    with patch("isycode.anthropic_provider.anthropic_stream_complete", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = mock_resp
        messages = [{"role": "user", "content": "Hi"}]
        result = await provider_complete(provider, messages, max_tokens=100)
        assert result == mock_resp
        mock_complete.assert_called_once()


@pytest.mark.asyncio
async def test_provider_complete_openai_compatible():
    provider = MagicMock()
    provider.name = "openai"
    provider.api_key = "test_key"
    provider.model = "gpt-4o"
    provider.reasoning_effort = None
    provider.token_limit_field = "max_tokens"
    provider.temperature_supported = True
    provider.base_url = "https://api.openai.com/v1"

    mock_resp = {"text": "OpenAI response", "tool_calls": []}
    with patch("isycode.chat_transport.async_stream_complete", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = mock_resp
        messages = [{"role": "user", "content": "Hi"}]
        result = await provider_complete(provider, messages, max_tokens=100)
        assert result == mock_resp
        mock_stream.assert_called_once()
