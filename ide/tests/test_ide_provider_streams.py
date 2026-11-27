"""Provider wire boundaries: real HTTP parsing with no account/network requests."""
import asyncio
import json

import httpx
import pytest

from core.agent.providers.base import ProviderConfig
from core.agent.providers.google import GoogleProvider
from core.agent.providers.ollama import OllamaProvider


class Credentials:
    def get(self, name):
        return "fixture-key"
    def clear(self):
        pass


def test_ollama_stream_preserves_tool_calls_and_native_arguments():
    async def run():
        provider = OllamaProvider(ProviderConfig("local", "ollama", "fixture", "http://fixture", auth="none"), Credentials())
        await provider.client.aclose()
        def handle(request):
            assert json.loads(request.content)["stream"] is True
            return httpx.Response(200, text='\n'.join(json.dumps(item) for item in [
                {"message": {"content": "Checking "}, "done": False},
                {"message": {"content": "file", "tool_calls": [{"function": {"name": "read", "arguments": {"path": "app.py"}}}]}, "done": False},
                {"message": {}, "done": True, "done_reason": "stop", "eval_count": 12},
            ]))
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            events = [event async for event in provider.stream_completion([{"role": "user", "content": "hello"}])]
            assert [e.text for e in events if e.kind == "text"] == ["Checking ", "file"]
            response = events[-1].response
            call = response.tool_calls[0]
            assert call.arguments == {"path": "app.py"}
            wire = provider.build_tool_messages(response, [{"tool_call_id": call.id, "content": "found"}])
            assert wire[0]["tool_calls"][0]["function"]["arguments"] == {"path": "app.py"}
            assert wire[1]["tool_name"] == "read"
        finally:
            await provider.close()
    asyncio.run(run())


def test_google_stream_preserves_function_thought_signature_in_next_request():
    async def run():
        provider = GoogleProvider(ProviderConfig("google", "google", "fixture", "https://fixture/v1beta"), Credentials())
        await provider.client.aclose()
        def handle(request):
            assert request.url.path.endswith(":streamGenerateContent")
            assert request.url.params["alt"] == "sse"
            assert "key" not in request.url.params
            assert request.headers["x-goog-api-key"] == "fixture-key"
            frames = [
                {"candidates": [{"content": {"parts": [{"text": "Checking "}]}}]},
                {"candidates": [{"content": {"parts": [{"functionCall": {"name": "read", "args": {"path": "app.py"}}, "thoughtSignature": "opaque-signature"}]}, "finishReason": "STOP"}]},
            ]
            return httpx.Response(200, text='\n\n'.join('data: '+json.dumps(f) for f in frames))
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            events = [event async for event in provider.stream_completion([{"role": "user", "content": "hello"}])]
            response = events[-1].response
            assert response.content == "Checking "
            call = response.tool_calls[0]
            wire = provider.build_tool_messages(response, [{"tool_call_id": call.id, "content": "found"}])
            payload = provider._payload(wire, None)
            assert payload["contents"][0]["parts"][1]["thoughtSignature"] == "opaque-signature"
            assert payload["contents"][1]["parts"][0]["functionResponse"]["name"] == "read"
        finally:
            await provider.close()
    asyncio.run(run())


def test_truncated_ollama_stream_never_returns_executable_tool_call():
    async def run():
        provider = OllamaProvider(ProviderConfig("local", "ollama", "fixture", "http://fixture", auth="none"), Credentials())
        await provider.client.aclose()
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=json.dumps({"message": {"content": "partial"}, "done": False}))))
        try:
            with pytest.raises(ValueError, match="completa"):
                _ = [e async for e in provider.stream_completion([{"role": "user", "content": "hi"}])]
        finally:
            await provider.close()
    asyncio.run(run())
