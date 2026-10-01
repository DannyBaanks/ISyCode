"""Native Anthropic Messages API transport for ISyCode's chat loop.

The rest of ISyCode keeps OpenAI-shaped chat messages; this module converts
them to the Messages API, streams through the official ``anthropic`` SDK, and
returns the same ``{"text", "tool_calls"}`` shape as the OpenAI transport.
It is only a transport: ProviderNetworkOwner still authorizes and receipts
every request, and tools still run through their own owners.

Thinking blocks produced during a tool loop are returned in
``anthropic_content`` and must be replayed unchanged on the next request of
the same turn. Earlier turns are sent as plain text, and in-turn context
trimming can edit history, so requests set ``prefix_mismatch_behavior`` to
``drop_block``: an invalidated thinking block is dropped instead of failing.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from isycode.providers import ProviderError
from isycode.streaming import StreamError

DEFAULT_MODEL = "claude-opus-5-5"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
# Models that take adaptive thinking and output_config.effort.
ADAPTIVE_THINKING_MODELS = frozenset({
    "claude-fable-5-1", "claude-fable-5", "claude-opus-5-5", "claude-opus-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-5-5",
    "claude-sonnet-5", "claude-sonnet-4-6",
})
# Server-side refusal fallback ("default" routing) on the Claude API.
FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                             "claude-sonnet-5-5"})
EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def sdk_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def to_anthropic(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Split leading system messages into ``system`` and convert the rest."""
    index = 0
    system_parts = []
    while index < len(messages) and messages[index].get("role") == "system":
        system_parts.append(str(messages[index].get("content") or ""))
        index += 1
    converted: list[dict[str, Any]] = []
    for message in messages[index:]:
        role = message.get("role")
        if role == "tool":
            result = {"type": "tool_result", "tool_use_id": message.get("tool_call_id", ""),
                      "content": str(message.get("content") or "")}
            previous = converted[-1] if converted else None
            # All results for one assistant turn go back in a single user message.
            if (previous and previous["role"] == "user" and isinstance(previous["content"], list)
                    and all(block.get("type") == "tool_result" for block in previous["content"])):
                previous["content"].append(result)
            else:
                converted.append({"role": "user", "content": [result]})
        elif role == "assistant":
            content = message.get("_anthropic_content")
            if not content:
                content = []
                if message.get("content"):
                    content.append({"type": "text", "text": message["content"]})
                for call in message.get("tool_calls") or []:
                    function = call.get("function", {})
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    content.append({"type": "tool_use", "id": call.get("id", ""),
                                    "name": function.get("name", ""), "input": arguments})
            converted.append({"role": "assistant", "content": content})
        elif role in {"user", "system"}:
            converted.append({"role": role, "content": str(message.get("content") or "")})
    return "\n\n".join(part for part in system_parts if part), converted


def to_anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result = []
    for tool in tools or []:
        function = tool.get("function", {})
        result.append({"name": function.get("name", ""),
                       "description": function.get("description", ""),
                       "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
                       # Inputs stream as generated; every ISyCode tool validates its own arguments.
                       "eager_input_streaming": True})
    return result


def request_options(model: str, effort: str | None) -> dict[str, Any]:
    """Thinking, effort, fallback and beta options for one model."""
    options: dict[str, Any] = {"betas": []}
    if model in ADAPTIVE_THINKING_MODELS:
        options["thinking"] = {"type": "adaptive", "display": "summarized",
                               "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
        options["output_config"] = {"effort": effort if effort in EFFORT_LEVELS else "medium"}
        options["betas"].append(THINKING_BINDING_BETA)
    if model in FALLBACK_MODELS:
        options["fallbacks"] = "default"
        options["betas"].append(FALLBACK_BETA)
    return options


def _tool_calls(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": block.get("id", ""), "type": "function", "function": {
        "name": block.get("name", ""),
        "arguments": json.dumps(block.get("input") if isinstance(block.get("input"), dict) else {},
                                ensure_ascii=False)}}
            for block in content if block.get("type") == "tool_use"]


def interpret(content: list[dict[str, Any]], stop_reason: str | None,
              stop_details: dict[str, Any] | None) -> dict[str, Any]:
    """Map a final message to ISyCode's response shape; never run truncated tool calls."""
    text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
    if stop_reason == "refusal":
        category = (stop_details or {}).get("category") or "unspecified"
        return {"text": f"Claude declined this request (category: {category}). Nothing was run.",
                "tool_calls": [], "stop_reason": stop_reason}
    calls = _tool_calls(content)
    if stop_reason == "max_tokens" and calls:
        return {"text": (text + "\n\n[The answer hit its length limit while writing a tool call; "
                         "the call was not run. Raise Answer length in Settings → My defaults.]"),
                "tool_calls": [], "stop_reason": stop_reason}
    return {"text": text, "tool_calls": calls, "anthropic_content": content,
            "stop_reason": stop_reason}


async def anthropic_stream_complete(api_key: str | None, model: str, messages: list[dict],
                                    *, max_tokens: int, effort: str | None = None,
                                    on_chunk: Callable[[str, str], None] | None = None,
                                    tools: list[dict] | None = None,
                                    base_url: str = ANTHROPIC_BASE_URL,
                                    client: Any = None) -> dict[str, Any]:
    """Stream one Messages API request and return ISyCode's response shape."""
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderError("the Anthropic provider needs the optional SDK: "
                            "pip install 'isycode[anthropic]'") from exc
    system, converted = to_anthropic(messages)
    options = request_options(model, effort)
    betas = options.pop("betas")
    request: dict[str, Any] = {"model": model, "max_tokens": max_tokens,
                               "messages": converted, **options}
    if system:
        request["system"] = system
    if tools:
        request["tools"] = to_anthropic_tools(tools)
    if betas:
        request["betas"] = betas
    client = client or anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
    try:
        async with client.beta.messages.stream(**request) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and on_chunk is not None:
                    if event.delta.type == "thinking_delta" and event.delta.thinking:
                        on_chunk("reasoning", event.delta.thinking)
                    elif event.delta.type == "text_delta":
                        on_chunk("content", event.delta.text)
            final = await stream.get_final_message()
    except ValueError as exc:
        # Eager tool input the SDK could not parse at all: there is no complete
        # tool_use to answer, so the turn fails and nothing runs.
        raise StreamError("the model's tool input could not be parsed; nothing was run") from exc
    except anthropic.AuthenticationError as exc:
        raise ProviderError("Anthropic rejected the API key", 401) from exc
    except anthropic.PermissionDeniedError as exc:
        raise ProviderError("this API key cannot use that model", 403) from exc
    except anthropic.NotFoundError as exc:
        raise ProviderError(f"model {model!r} was not found", 404) from exc
    except anthropic.RateLimitError as exc:
        raise ProviderError("Anthropic rate limit reached; try again shortly", 429) from exc
    except anthropic.APIStatusError as exc:
        raise ProviderError(f"Anthropic API error {exc.status_code}", exc.status_code) from exc
    except anthropic.APIConnectionError as exc:
        raise ProviderError("could not reach the Anthropic API", transport=True) from exc
    content = [block.to_dict() for block in final.content]
    details = final.stop_details.to_dict() if getattr(final, "stop_details", None) else None
    response = interpret(content, final.stop_reason, details)
    usage = getattr(final, "usage", None)
    response["usage"] = usage.to_dict() if usage is not None else None
    return response


def list_models(api_key: str | None, base_url: str = ANTHROPIC_BASE_URL) -> list[str]:
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderError("the Anthropic provider needs the optional SDK: "
                            "pip install 'isycode[anthropic]'") from exc
    try:
        client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        return sorted(model.id for model in client.models.list())
    except anthropic.APIStatusError as exc:
        raise ProviderError("Anthropic model catalog request failed", exc.status_code) from exc
    except anthropic.APIConnectionError as exc:
        raise ProviderError("Anthropic model catalog is unavailable", transport=True) from exc


__all__ = ["DEFAULT_MODEL", "anthropic_stream_complete", "interpret", "list_models",
           "request_options", "sdk_available", "to_anthropic", "to_anthropic_tools"]
