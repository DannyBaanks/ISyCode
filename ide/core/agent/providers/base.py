"""Base provider classes."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
import httpx
import json
import uuid


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    provider_type: str
    model: str
    endpoint: str
    timeout: float = 30.0
    max_tokens: int = 4096
    temperature: float = 0.7
    extra_headers: dict = field(default_factory=dict)
    auth: str = "api_key"

    def url_for(self, path: str) -> str:
        """The URL to call, whether `endpoint` is a base or already complete.

        `endpoint` has always been ambiguous: some providers store
        "https://host/v1" and some store the full "https://host/v1/chat/
        completions". Each provider guessed differently, and the one that
        guessed "always append" sent every request to
        ".../chat/completions/chat/completions" and got a 404 with no visible
        error.

        Accepting both shapes here is the fix, because the ambiguity lives in
        stored config that already exists on users' machines; rejecting one
        shape would break whoever has it saved.
        """
        if not self.endpoint:
            raise ValueError(
                f"provider '{self.name}' has no endpoint configured; "
                "set one with: isyvm agent provider add"
            )
        base = self.endpoint.rstrip("/")
        suffix = "/" + path.strip("/")
        if base.endswith(suffix):
            return base
        return base + suffix

    def base_url(self, suffix: str = "/v1") -> str:
        """`endpoint` with a trailing path segment removed, if present.

        Exists because `str.rstrip("/v1")` strips a *character set*, not a
        suffix: it also eats a host ending in 'v' or '1'.
        """
        base = self.endpoint.rstrip("/")
        marker = "/" + suffix.strip("/")
        if base.endswith(marker):
            return base[: -len(marker)]
        return base


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list = None
    tool_call_id: str = None


@dataclass
class CompletionResponse:
    content: str
    tool_calls: list = None
    finish_reason: str = "stop"
    usage: dict = None
    wire: dict | None = None


class ProviderError(ValueError):
    """Public protocol diagnostic: code/message are host constants, never SDK bodies."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.public_message = message
        super().__init__(message)


@dataclass(frozen=True)
class ProviderEvent:
    kind: str
    text: str = ""
    response: CompletionResponse | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


class BaseProvider(ABC):
    def __init__(self, config: ProviderConfig, secret_broker):
        self.config = config
        self.secret_broker = secret_broker
        self.client = httpx.AsyncClient(timeout=config.timeout)
    
    @abstractmethod
    async def complete(self, messages: list[dict], tools: list = None) -> CompletionResponse:
        pass
    
    @abstractmethod
    async def stream(self, messages: list[dict], tools: list = None) -> AsyncIterator[str]:
        pass

    async def stream_completion(self, messages: list[dict], tools: list = None):
        """Compatibility fallback preserves tool calls; it does not fake streaming."""
        response = await self.complete(messages, tools)
        if response.content:
            yield ProviderEvent("text", response.content)
        yield ProviderEvent("completed", response=response)

    def build_tool_messages(self, response: CompletionResponse, results: list[dict]) -> list[dict]:
        """Serialize an assistant tool call and its results for the next turn.

        The default shape is the OpenAI-compatible message format. Providers
        with a different wire contract override this method.
        """
        assistant_calls = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in (response.tool_calls or [])
        ]
        assistant = {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": assistant_calls,
        }
        tool_messages = [
            {
                "role": "tool",
                "tool_call_id": item["tool_call_id"],
                "content": item["content"],
            }
            for item in results
        ]
        return [assistant, *tool_messages]
    
    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        # Ollama is anonymous/local; others require API key via secret broker
        if self.config.provider_type == "ollama" or self.config.auth == "none":
            return headers
        return self.secret_broker.inject_into_headers(self.config.name, headers)
    
    async def close(self):
        await self.client.aclose()
        clear = getattr(self.secret_broker, "clear", None)
        if clear:
            clear()


def convert_tool_calls_openai(tool_calls: list) -> list[ToolCall]:
    """Convert OpenAI tool calls to standard format."""
    return [
        ToolCall(
            id=tc.get("id") or uuid.uuid4().hex,
            name=tc["function"]["name"],
            arguments=tc["function"]["arguments"] if isinstance(tc["function"]["arguments"], dict) 
                      else __import__("json").loads(tc["function"]["arguments"])
        )
        for tc in tool_calls
    ]


def convert_tool_calls_anthropic(content: list) -> list[ToolCall]:
    """Convert Anthropic tool calls to standard format."""
    return [
        ToolCall(
            id=block.id,
            name=block.name,
            arguments=block.input
        )
        for block in content if block.type == "tool_use"
    ]
