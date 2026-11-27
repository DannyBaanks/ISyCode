"""Test provider adapters against a mock HTTP server (OpenAI + Ollama formats)."""

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent.providers import ProviderConfig, ProviderRegistry
from core.agent.providers.base import BaseProvider
from core.secret_broker import SecretBroker


class MockOpenAIServer(BaseHTTPRequestHandler):
    """Simulates OpenAI /chat/completions with tool call support."""
    
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        auth = self.headers.get("Authorization", "")
        
        if "/chat/completions" not in self.path:
            self.send_response(404)
            self.end_headers()
            return
        
        # Check auth came through (proves secret broker injection)
        assert auth == "Bearer sk-test-key-123", f"Bad auth: {auth!r}"
        assert body["model"] == "gpt-test"
        
        tools_included = "tools" in body and body["tools"]
        
        # First call with tools -> respond with a tool call
        if tools_included:
            response = {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-test",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read", "arguments": json.dumps({"path": "a.txt"})}
                        }]
                    },
                    "finish_reason": "tool_calls"
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            }
        else:
            response = {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-test",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "Final answer"},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            }
        
        data = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    
    def log_message(self, *args):
        pass


class MockOllamaServer(BaseHTTPRequestHandler):
    """Simulates Ollama /api/chat (no auth required)."""
    
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        
        if "/api/chat" not in self.path:
            self.send_response(404)
            self.end_headers()
            return
        
        # No Authorization header should exist for local
        assert not self.headers.get("Authorization"), "Ollama should not get auth headers"
        assert body["model"] == "llama-test"
        
        response = {
            "model": "llama-test",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "Ollama answer"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 5,
            "eval_count": 5
        }
        data = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    
    def log_message(self, *args):
        pass


def start_server(handler_cls, port):
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


async def _test_openai(config_dir):
    print("=== Test OpenAI-style (with secret broker injection) ===")
    server = start_server(MockOpenAIServer, 18081)
    
    broker = SecretBroker()
    broker.set("mock-openai", "sk-test-key-123")
    
    registry = ProviderRegistry(broker, config_path=Path(config_dir) / "test-config.yaml")
    registry.add("mock-openai", "openai", "gpt-test", endpoint="http://127.0.0.1:18081/v1")
    
    provider = registry.get("mock-openai")
    tools = [{"type": "function", "function": {"name": "read", "description": "read", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]
    
    # Call 1: should return tool call
    resp1 = await provider.complete(
        [{"role": "user", "content": "read the file"}],
        tools=tools
    )
    assert resp1.tool_calls, "Expected tool call"
    assert resp1.tool_calls[0].name == "read"
    assert resp1.tool_calls[0].arguments == {"path": "a.txt"}
    print(f"  Tool call: {resp1.tool_calls[0]}")
    
    # Call 2: no tools -> final answer
    resp2 = await provider.complete([{"role": "user", "content": "hi"}])
    assert resp2.content == "Final answer"
    print(f"  Final: {resp2.content!r}")
    
    server.shutdown()
    print("  OK")


async def _test_ollama(config_dir):
    print("=== Test Ollama-style (anonymous local) ===")
    server = start_server(MockOllamaServer, 18082)
    
    broker = SecretBroker()
    registry = ProviderRegistry(broker, config_path=Path(config_dir) / "test-config.yaml")
    registry.add("mock-ollama", "ollama", "llama-test", endpoint="http://127.0.0.1:18082")
    
    provider = registry.get("mock-ollama")
    resp = await provider.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "Ollama answer"
    print(f"  Response: {resp.content!r}")
    
    server.shutdown()
    print("  OK")


async def main():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        await _test_openai(td)
        await _test_ollama(td)
    broker = SecretBroker()
    broker.remove("mock-openai")
    broker.remove("mock-ollama")
    print("\nALL PROVIDER TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())


def test_openai(tmp_path):
    asyncio.run(_test_openai(tmp_path))


def test_ollama(tmp_path):
    asyncio.run(_test_ollama(tmp_path))
