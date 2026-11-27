"""Ollama provider implementation."""

from __future__ import annotations
from typing import AsyncIterator
import json
from .base import BaseProvider, ProviderConfig, CompletionResponse, ProviderEvent, ToolCall, convert_tool_calls_openai


class OllamaProvider(BaseProvider):
    def build_tool_messages(self, response, results):
        names = {call.id: call.name for call in response.tool_calls or []}
        return [{"role": "assistant", "content": response.content,
                 "thinking": (response.wire or {}).get("thinking", ""),
                 "tool_calls": [{"function": {"name": call.name, "arguments": call.arguments}} for call in response.tool_calls or []]},
                *[{"role": "tool", "tool_name": names[item["tool_call_id"]], "content": item["content"]} for item in results]]

    async def stream_completion(self, messages, tools=None):
        payload = {"model": self.config.model, "messages": messages, "stream": True,
                   "options": {"temperature": self.config.temperature, "num_predict": self.config.max_tokens}}
        if tools:
            payload["tools"] = tools
        text, thinking, calls, total, terminal, usage, finish = [], [], [], 0, False, None, "stop"
        async with self.client.stream("POST", self.config.url_for("/api/chat"), headers=self._build_headers(), json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                total += len(line)
                if total > 8_000_000:
                    raise ValueError("La respuesta supera el límite de streaming.")
                data = json.loads(line)
                if "error" in data:
                    raise ValueError("Ollama rechazó la generación.")
                message = data.get("message", {})
                for field, values in (("content", text), ("thinking", thinking)):
                    value = message.get(field, "")
                    if not isinstance(value, str):
                        raise ValueError("Fragmento de Ollama inválido.")
                    if value:
                        values.append(value)
                        if field == "content":
                            yield ProviderEvent("text", value)
                for call in convert_tool_calls_openai(message.get("tool_calls") or []):
                    if not call.name or not isinstance(call.arguments, dict) or len(calls) >= 128:
                        raise ValueError("Herramienta de Ollama inválida.")
                    calls.append(call)
                if data.get("done") is True:
                    terminal = True
                    finish = data.get("done_reason", "stop")
                    usage = {"prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": data.get("eval_count")}
                    break
        if not terminal:
            raise ValueError("El streaming terminó sin una respuesta completa.")
        yield ProviderEvent("completed", response=CompletionResponse("".join(text), calls or None, finish, usage, {"thinking": "".join(thinking)}))

    async def complete(self, messages: list[dict], tools: list = None) -> CompletionResponse:
        headers = self._build_headers()
        payload = {
            "model": self.config.model,
            "messages": messages,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        
        resp = await self.client.post(
            f"{self.config.endpoint.rstrip('/')}/api/chat",
            headers=headers,
            json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        
        msg = data.get("message", {})
        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = convert_tool_calls_openai(msg["tool_calls"])
        
        return CompletionResponse(
            content=msg.get("content", ""),
            tool_calls=tool_calls,
            finish_reason=data.get("done_reason", "stop"),
            usage={"prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": data.get("eval_count")}
        )
    
    async def stream(self, messages: list[dict], tools: list = None) -> AsyncIterator[str]:
        headers = self._build_headers()
        payload = {
            "model": self.config.model,
            "messages": messages,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        
        async with self.client.stream(
            "POST",
            f"{self.config.endpoint.rstrip('/')}/api/chat",
            headers=headers,
            json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if data.get("message", {}).get("content"):
                            yield data["message"]["content"]
                        if data.get("done"):
                            break
                    except Exception:
                        pass
