"""OpenAI provider implementation."""

from __future__ import annotations
import json
from typing import AsyncIterator
from .base import BaseProvider, ProviderConfig, CompletionResponse, ProviderEvent, ProviderError, ToolCall, convert_tool_calls_openai


class OpenAIProvider(BaseProvider):
    async def stream_completion(self, messages: list[dict], tools: list = None):
        payload = {"model": self.config.model, "messages": messages,
                   "temperature": self.config.temperature, "max_tokens": self.config.max_tokens,
                   "stream": True}
        if tools:
            payload.update({"tools": tools, "tool_choice": "auto"})
        text, calls, usage, finish = [], {}, None, "stop"
        total, terminal, saw_choice = 0, False, False
        async with self.client.stream("POST", self.config.url_for("/chat/completions"),
                                      headers=self._build_headers(), json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    terminal = True
                    break
                total += len(raw)
                if total > 8_000_000:
                    raise ProviderError("PROVIDER_SIZE_LIMIT", "La respuesta del provider supera el límite de tamaño.")
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ProviderError("PROVIDER_INVALID_JSON", "El provider envió un evento JSON inválido.") from exc
                if not isinstance(chunk, dict):
                    raise ProviderError("PROVIDER_INVALID_EVENT", "El provider envió un evento con formato inválido.")
                if "error" in chunk:
                    raise ProviderError("PROVIDER_STREAM_ERROR", "El provider notificó un error durante el streaming.")
                usage = chunk.get("usage") or usage
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                if not isinstance(choices, list) or not isinstance(choices[0], dict):
                    raise ProviderError("PROVIDER_INVALID_EVENT", "El provider envió choices con formato inválido.")
                choice = choices[0]
                saw_choice = True
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    raise ProviderError("PROVIDER_INVALID_EVENT", "El provider envió delta con formato inválido.")
                # Only explicitly returned provider output; never infer reasoning
                # from activity or mix it into the final answer/tool arguments.
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(reasoning, str) and reasoning:
                    yield ProviderEvent("reasoning", reasoning)
                elif reasoning:
                    yield ProviderEvent("activity", "provider_activity")
                finish = choice.get("finish_reason") or finish
                terminal = terminal or bool(choice.get("finish_reason"))
                if delta.get("content"):
                    value = delta["content"]
                    if not isinstance(value, str):
                        raise ProviderError("PROVIDER_INVALID_CONTENT", "Contenido de streaming inválido.")
                    text.append(value)
                    yield ProviderEvent("text", value)
                for fragment in delta.get("tool_calls", []):
                    yield ProviderEvent("activity", "tool_arguments")
                    index = fragment["index"]
                    if not isinstance(index, int) or not 0 <= index < 128:
                        raise ProviderError("PROVIDER_TOOL_ARGUMENTS", "Índice de herramienta inválido.")
                    call = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    if fragment.get("id"):
                        call["id"] = fragment["id"]
                    function = fragment.get("function", {})
                    for field in ("name", "arguments"):
                        if function.get(field):
                            if not isinstance(function[field], str):
                                raise ProviderError("PROVIDER_TOOL_ARGUMENTS", "Fragmento de herramienta inválido.")
                            call["function"][field] += function[field]
        if not terminal or not saw_choice:
            raise ProviderError("PROVIDER_STREAM_INCOMPLETE", "El streaming terminó sin una respuesta completa. La salida recibida es parcial.")
        if finish == "length":
            raise ProviderError("PROVIDER_TOKEN_LIMIT", "El modelo agotó max_tokens. La salida es parcial; revisa el límite del provider. No se ejecutaron llamadas incompletas.")
        try:
            tools_out = convert_tool_calls_openai([calls[index] for index in sorted(calls)]) if calls else None
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderError("PROVIDER_TOOL_ARGUMENTS", "El modelo devolvió argumentos de herramienta inválidos. Esa respuesta no se ejecutó.") from exc
        for call in tools_out or []:
            if not call.name or not isinstance(call.arguments, dict):
                raise ProviderError("PROVIDER_TOOL_ARGUMENTS", "La herramienta no contiene argumentos completos.")
        yield ProviderEvent("completed", response=CompletionResponse("".join(text), tools_out, finish, usage))

    async def complete(self, messages: list[dict], tools: list = None) -> CompletionResponse:
        headers = self._build_headers()
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        resp = await self.client.post(
            self.config.url_for("/chat/completions"),
            headers=headers,
            json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        
        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = convert_tool_calls_openai(msg["tool_calls"])
        
        return CompletionResponse(
            content=msg.get("content", "") or "",
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=data.get("usage")
        )
    
    async def stream(self, messages: list[dict], tools: list = None) -> AsyncIterator[str]:
        headers = self._build_headers()
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        async with self.client.stream(
            "POST",
            self.config.url_for("/chat/completions"),
            headers=headers,
            json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"]
                        if delta.get("content"):
                            yield delta["content"]
                    except Exception:
                        pass
