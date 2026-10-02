"""Pick the wire protocol for the selected provider: OpenAI-compatible or Anthropic Messages.

Callers keep one message shape (OpenAI chat messages) and one response shape
(``{"text", "tool_calls"}``); authorization stays with ProviderNetworkOwner.
"""
from __future__ import annotations

from typing import Any, Callable

from isycode.providers import PRESETS
from isycode.streaming import async_stream_complete


def uses_anthropic(provider: Any) -> bool:
    return PRESETS.get(getattr(provider, "name", ""), {}).get("api") == "anthropic"


async def provider_complete(provider: Any, messages: list[dict], *, max_tokens: int | None = None,
                            on_chunk: Callable[[str, str], None] | None = None,
                            tools: list[dict] | None = None) -> dict:
    if PRESETS.get(getattr(provider, 'name', ''), {}).get('api') == 'codex':
        from pathlib import Path
        from isycode.codex_connector import CodexConnector
        identity = provider.connector_identity
        async with CodexConnector(identity['executable'], Path(identity['home'])) as connector:
            return await connector.complete(provider.model, messages, tools, on_chunk)
    if uses_anthropic(provider):
        from isycode.anthropic_provider import anthropic_stream_complete

        return await anthropic_stream_complete(
            provider.api_key, provider.model, messages, max_tokens=max_tokens,
            effort=provider.reasoning_effort, on_chunk=on_chunk, tools=tools,
            base_url=provider.base_url, timeout_s=None)
    return await async_stream_complete(
        provider.base_url, provider.api_key, provider.model, messages, max_tokens=max_tokens,
        token_limit_field=provider.token_limit_field,
        reasoning_effort=provider.reasoning_effort,
        temperature_supported=provider.temperature_supported,
        timeout_s=None,
        on_chunk=on_chunk, tools=tools, include_usage=provider.name == "openai")


def assistant_turn(response: dict) -> dict:
    """The assistant message to append before tool results, replay data included."""
    message = {"role": "assistant", "content": response.get("text") or None,
               "tool_calls": response.get("tool_calls", [])}
    if response.get("anthropic_content"):
        # Thinking blocks must go back unchanged within the same turn.
        message["_anthropic_content"] = response["anthropic_content"]
    return message


__all__ = ["assistant_turn", "provider_complete", "uses_anthropic"]
