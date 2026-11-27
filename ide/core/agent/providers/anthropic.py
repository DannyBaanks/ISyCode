"""Anthropic provider implementation."""

from __future__ import annotations
from typing import AsyncIterator
import anthropic
import inspect
from .base import BaseProvider, ProviderConfig, CompletionResponse, ProviderEvent, ToolCall


class AnthropicProvider(BaseProvider):
    async def stream_completion(self, messages: list[dict], tools: list = None):
        client = self._get_client()
        kwargs = {"model": self.config.model,
                  "messages": [message for message in messages if message["role"] != "system"],
                  "system": next((message["content"] for message in messages if message["role"] == "system"), ""),
                  "max_tokens": self.config.max_tokens}
        if "temperature" in inspect.signature(client.messages.stream).parameters:
            kwargs["temperature"] = self.config.temperature
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        async with client.messages.stream(**kwargs) as stream:
            async for value in stream.text_stream:
                yield ProviderEvent("text", value)
            message = await stream.get_final_message()
        content, calls = [], []
        for block in message.content:
            if block.type == "text":
                content.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, block.input))
        yield ProviderEvent("completed", response=CompletionResponse("".join(content), calls or None, message.stop_reason,
                            {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}))

    def __init__(self, config: ProviderConfig, secret_broker):
        super().__init__(config, secret_broker)
        self._client = None

    def _get_client(self):
        if self._client is None:
            key = self.secret_broker.get(self.config.name)
            if not key:
                raise ValueError(f"No API key for {self.config.name}")
            self._client = anthropic.AsyncAnthropic(
                api_key=key,
                base_url=self.config.base_url("/v1") if self.config.endpoint else None,
                timeout=self.config.timeout,
                http_client=anthropic.DefaultAsyncHttpxClient(follow_redirects=False)
            )
        return self._client

    async def complete(self, messages: list[dict], tools: list = None) -> CompletionResponse:
        client = self._get_client()

        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        msgs = [m for m in messages if m["role"] != "system"]

        kwargs = {
            "model": self.config.model,
            "messages": msgs,
            "system": system,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        if "temperature" in inspect.signature(client.messages.create).parameters:
            kwargs["temperature"] = self.config.temperature
        resp = await client.messages.create(**kwargs)

        content = ""
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input
                ))

        return CompletionResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=resp.stop_reason,
            usage={"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        )

    def _convert_tools(self, tools: list) -> list:
        """Convert OpenAI-style tools to Anthropic format."""
        converted = []
        for t in tools:
            if t.get("type") == "function":
                f = t["function"]
                converted.append({
                    "name": f["name"],
                    "description": f.get("description", ""),
                    "input_schema": f.get("parameters", {"type": "object", "properties": {}})
                })
        return converted

    def build_tool_messages(self, response, results: list[dict]) -> list[dict]:
        content = []
        if response.content:
            content.append({"type": "text", "text": response.content})
        for call in response.tool_calls or []:
            content.append({
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": call.arguments,
            })
        return [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": item["tool_call_id"],
                        "content": item["content"],
                    }
                    for item in results
                ],
            },
        ]

    async def stream(self, messages: list[dict], tools: list = None) -> AsyncIterator[str]:
        async for event in self.stream_completion(messages, tools):
            if event.kind == "text":
                yield event.text

    async def close(self):
        if self._client:
            await self._client.close()
        await super().close()
