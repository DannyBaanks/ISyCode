"""Google (Gemini) provider implementation."""

from __future__ import annotations
from typing import AsyncIterator
import httpx
import json
import copy
import uuid
from .base import BaseProvider, ProviderConfig, CompletionResponse, ProviderEvent, ToolCall


class GoogleProvider(BaseProvider):
    def _build_headers(self):
        key = self.secret_broker.get(self.config.name)
        if not key:
            raise ValueError("Configura una clave API de Google.")
        return {"Content-Type": "application/json", "x-goog-api-key": key}

    def build_tool_messages(self, response, results):
        calls = {call.id: call.name for call in response.tool_calls or []}
        parts = (response.wire or {}).get("parts")
        if parts is None:
            parts = ([{"text": response.content}] if response.content else []) + [
                {"functionCall": {"name": call.name, "args": call.arguments}}
                for call in response.tool_calls or []]
        return [{"role": "assistant", "content": response.content, "provider_parts": copy.deepcopy(parts)},
                *[{"role": "tool", "name": calls[item["tool_call_id"]], "tool_call_id": item["tool_call_id"],
                   "content": item["content"]} for item in results]]

    def _payload(self, messages, tools):
        contents, system = [], []
        for message in messages:
            role = message["role"]
            if role == "system":
                system.append(message["content"])
                continue
            if role not in {"user", "assistant", "tool"}:
                raise ValueError("Rol no soportado por Gemini.")
            if role == "tool":
                parts = [{"functionResponse": {"name": message["name"], "response": {"result": message["content"]}}}]
            elif "provider_parts" in message:
                parts = copy.deepcopy(message["provider_parts"])
            else:
                parts = [{"text": message["content"]}]
            contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        payload = {"contents": contents, "generationConfig": {"temperature": self.config.temperature,
                    "maxOutputTokens": self.config.max_tokens}}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [tool["function"] for tool in tools if tool.get("type") == "function"]}]
        return payload

    def _response(self, parts, finish, usage):
        text, calls = [], []
        for part in parts:
            if "text" in part and not part.get("thought"):
                if not isinstance(part["text"], str):
                    raise ValueError("Texto de Gemini inválido.")
                text.append(part["text"])
            if "functionCall" in part:
                call = part["functionCall"]
                if not isinstance(call.get("name"), str) or not call["name"] or not isinstance(call.get("args", {}), dict) or len(calls) >= 128:
                    raise ValueError("Herramienta de Gemini inválida.")
                calls.append(ToolCall(call.get("id") or uuid.uuid4().hex, call["name"], call.get("args", {})))
        return CompletionResponse("".join(text), calls or None, finish, usage, {"parts": copy.deepcopy(parts)})

    async def stream_completion(self, messages, tools=None):
        parts, terminal, total, usage, finish = [], False, 0, None, "STOP"
        url = self.config.url_for(f"/models/{self.config.model}:streamGenerateContent")
        async with self.client.stream("POST", url, params={"alt": "sse"}, headers=self._build_headers(), json=self._payload(messages, tools)) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                total += len(raw)
                if total > 8_000_000:
                    raise ValueError("La respuesta supera el límite de streaming.")
                data = json.loads(raw)
                if "error" in data or data.get("promptFeedback", {}).get("blockReason"):
                    raise ValueError("Gemini rechazó la generación.")
                usage = data.get("usageMetadata") or usage
                candidates = data.get("candidates", [])
                if not candidates:
                    continue
                candidate = candidates[0]
                for part in candidate.get("content", {}).get("parts", []):
                    parts.append(part)
                    if "text" in part and not part.get("thought"):
                        yield ProviderEvent("text", part["text"])
                if candidate.get("finishReason"):
                    terminal, finish = True, candidate["finishReason"]
        if not terminal:
            raise ValueError("El streaming terminó sin una respuesta completa.")
        yield ProviderEvent("completed", response=self._response(parts, finish, usage))

    async def complete(self, messages: list[dict], tools: list = None) -> CompletionResponse:
        headers = self._build_headers()
        
        payload = self._payload(messages, tools)

        url = self.config.url_for(f"/models/{self.config.model}:generateContent")
        resp = await self.client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        candidate = data["candidates"][0]
        return self._response(candidate["content"]["parts"], candidate.get("finishReason", "STOP"), data.get("usageMetadata"))

    async def stream(self, messages: list[dict], tools: list = None) -> AsyncIterator[str]:
        # Similar to complete but with streamGenerateContent
        # Simplified for brevity
        result = await self.complete(messages, tools)
        if result.content:
            yield result.content
