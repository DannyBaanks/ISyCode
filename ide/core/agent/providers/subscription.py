"""Subscription generation yields proposals for the common IDE execution owner."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .base import BaseProvider, CompletionResponse, ProviderEvent, ToolCall, convert_tool_calls_openai
from .openai import OpenAIProvider
from core.connectors.codex import CodexConnector
from core.subscriptions import ENDPOINTS, SubscriptionService, SubscriptionError
from core.processes import capture_process


class SubscriptionProvider(BaseProvider):
    def __init__(self, config, secret_broker):
        super().__init__(config, secret_broker)
        self.accounts = SubscriptionService()

    async def complete(self, messages, tools=None):
        if self.config.provider_type == "codex-subscription":
            identity = self.accounts.identity(self.config.provider_type)
            async with CodexConnector(identity["executable"], Path(identity["home"]), timeout_s=self.config.timeout) as peer:
                response = await peer.complete(self.config.model, messages, tools)
            return CompletionResponse(response["text"], convert_tool_calls_openai(response["tool_calls"]) or None,
                                      "tool_calls" if response["tool_calls"] else "stop", response.get("usage"))
        if self.config.provider_type == "grok-subscription":
            async for event in self.stream_completion(messages, tools):
                if event.kind == "completed":
                    return event.response
            raise SubscriptionError("La sesión no devolvió una respuesta completa.")
        identity = self.accounts.identity(self.config.provider_type)
        account = await self.accounts.inspect(self.config.provider_type)
        if not account["authenticated"]:
            raise SubscriptionError("Inicia sesión Claude en Providers → Suscripciones. No hay fallback a API de pago.")
        names = [tool["function"]["name"] for tool in tools or []]
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {"text": {"type": "string"}, "tool_calls": {"type": "array", "maxItems": 16,
                  "items": {"type": "object", "required": ["name", "arguments"], "additionalProperties": False,
                            "properties": {"name": {"type": "string", "enum": names} if names else {"type": "string"},
                                           "arguments": {"type": "object"}}}}}, "required": ["text", "tool_calls"]}
        prompt = json.dumps({"contract": "Continue the transcript. Tool calls are proposals for the IDE host. Built-in tools are unavailable. Return text or declared tool_calls; never simulate execution.",
                             "messages": messages, "tools": tools or []}, ensure_ascii=False).encode()
        if len(prompt) > 8_000_000:
            raise SubscriptionError("El contexto supera el límite del conector.")
        output = await capture_process(self.accounts.claude_command(identity, self.config.model, schema), input_data=prompt,
                                       cwd=identity["home"], env=self.accounts.environment(identity), timeout=self.config.timeout, limit=8_000_000)
        if output.returncode:
            raise SubscriptionError("Claude rechazó el turno. Comprueba sesión, límites o versión del CLI.")
        data = json.loads(output.stdout)
        response = data.get("structured_output") if isinstance(data, dict) and not data.get("is_error") else None
        if not isinstance(response, dict) or not isinstance(response.get("text"), str) or not isinstance(response.get("tool_calls"), list) or len(response["tool_calls"]) > 16:
            raise SubscriptionError("Claude no devolvió propuestas estructuradas válidas.")
        calls = []
        import uuid
        for call in response["tool_calls"]:
            if not isinstance(call, dict) or call.get("name") not in names or not isinstance(call.get("arguments"), dict):
                raise SubscriptionError("Claude solicitó una herramienta no declarada.")
            calls.append(ToolCall(uuid.uuid4().hex, call["name"], call["arguments"]))
        return CompletionResponse(response["text"], calls or None, "tool_calls" if calls else "stop")

    async def stream_completion(self, messages, tools=None):
        if self.config.provider_type == "grok-subscription":
            identity = self.accounts.identity(self.config.provider_type)
            token = self.accounts.grok_token(identity)
            if not token:
                raise SubscriptionError("Sesión Grok ausente o expirada. Inicia sesión con el CLI oficial desde Providers.")
            # Reuse the OpenAI-compatible parser; endpoint is fixed, redirects off.
            class Credentials:
                def inject_into_headers(self, name, headers):
                    return {**headers, "Authorization": "Bearer " + token}
            from dataclasses import replace
            config = replace(self.config, provider_type="openai-compatible", endpoint=ENDPOINTS["grok-subscription"], auth="api_key")
            peer = OpenAIProvider(config, Credentials())
            try:
                async for event in peer.stream_completion(messages, tools):
                    yield event
            finally:
                await peer.close()
            return
        if self.config.provider_type != "codex-subscription":
            response = await self.complete(messages, tools)
            if response.content:
                yield ProviderEvent("text", response.content)
            yield ProviderEvent("completed", response=response)
            return
        identity = self.accounts.identity(self.config.provider_type)
        queue = asyncio.Queue(maxsize=64)
        async def generate():
            try:
                async with CodexConnector(identity["executable"], Path(identity["home"]), timeout_s=self.config.timeout) as peer:
                    def chunk(kind, value):
                        if kind == "content":
                            queue.put_nowait(ProviderEvent("text", value))
                    result = await peer.complete(self.config.model, messages, tools, chunk)
                response = CompletionResponse(result["text"], convert_tool_calls_openai(result["tool_calls"]) or None,
                                              "tool_calls" if result["tool_calls"] else "stop", result.get("usage"))
                await queue.put(ProviderEvent("completed", response=response))
            except Exception:
                await queue.put(SubscriptionError("Codex no pudo completar el turno. Revisa el perfil y su sesión de ChatGPT."))
        task = asyncio.create_task(generate())
        try:
            while True:
                event = await queue.get()
                if isinstance(event, Exception):
                    raise event
                yield event
                if event.kind == "completed":
                    break
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def stream(self, messages, tools=None):
        async for event in self.stream_completion(messages, tools):
            if event.kind == "text":
                yield event.text

    async def list_models(self):
        report = await self.accounts.inspect(self.config.provider_type)
        return report["models"]
