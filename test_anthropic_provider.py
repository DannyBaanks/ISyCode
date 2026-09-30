"""Native Anthropic transport: message conversion, request options, SSE parsing, replay."""
import asyncio
import json

import pytest

from isycode.anthropic_provider import (
    FALLBACK_BETA, THINKING_BINDING_BETA, interpret, request_options, to_anthropic,
    to_anthropic_tools,
)
from isycode.chat_transport import assistant_turn, uses_anthropic
from isycode.providers import PRESETS, Provider


def test_leading_system_messages_become_system_and_tool_results_are_grouped():
    messages = [
        {"role": "system", "content": "a"}, {"role": "system", "content": "b"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "workspace_read", "arguments": '{"path": "x"}'}},
            {"id": "t2", "type": "function", "function": {"name": "workspace_list", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "one"},
        {"role": "tool", "tool_call_id": "t2", "content": "two"},
    ]
    system, converted = to_anthropic(messages)
    assert system == "a\n\nb"
    assert converted[1]["content"][0] == {"type": "tool_use", "id": "t1", "name": "workspace_read",
                                          "input": {"path": "x"}}
    assert converted[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "one"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "two"}]}


def test_thinking_blocks_are_replayed_unchanged_within_a_turn():
    raw = [{"type": "thinking", "thinking": "plan", "signature": "sig"},
           {"type": "tool_use", "id": "t1", "name": "workspace_read", "input": {"path": "x"}}]
    response = interpret(raw, "tool_use", None)
    turn = assistant_turn(response)
    _, converted = to_anthropic([{"role": "user", "content": "q"}, turn])
    assert converted[1]["content"] == raw
    assert json.loads(response["tool_calls"][0]["function"]["arguments"]) == {"path": "x"}


def test_refusals_and_truncated_tool_calls_never_run_tools():
    refused = interpret([{"type": "text", "text": "partial"}], "refusal", {"category": "cyber"})
    assert refused["tool_calls"] == [] and "cyber" in refused["text"]
    cut = interpret([{"type": "tool_use", "id": "t", "name": "workspace_write", "input": {"path": "a"}}],
                    "max_tokens", None)
    assert cut["tool_calls"] == [] and "not run" in cut["text"]


def test_request_options_follow_the_model():
    opus = request_options("claude-opus-5-5", "high")
    assert opus["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert opus["output_config"] == {"effort": "high"} and opus["fallbacks"] == "default"
    assert opus["betas"] == [THINKING_BINDING_BETA, FALLBACK_BETA]
    assert request_options("claude-opus-5-5", "bogus")["output_config"] == {"effort": "medium"}
    haiku = request_options("claude-haiku-4-5", "high")
    assert haiku == {"betas": []}
    tool = to_anthropic_tools([{"type": "function", "function": {
        "name": "n", "description": "d", "parameters": {"type": "object"}}}])[0]
    assert tool == {"name": "n", "description": "d", "input_schema": {"type": "object"},
                    "eager_input_streaming": True}


def test_preset_is_registered_for_classic_hosts_and_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.delenv("ISYCODE_BASE_URL", raising=False)
    monkeypatch.delenv("ISYMOTRON_BASE_URL", raising=False)
    provider = Provider(name="anthropic", model=None, api_key="test-not-real")
    assert uses_anthropic(provider) and provider.base_url == "https://api.anthropic.com"
    assert PRESETS["anthropic"]["default_model"] == "claude-opus-5-5"
    from isycode.credential_owner import credential_services
    from isycode.workspace_authority import _known_provider_hosts
    assert "anthropic" in credential_services()
    assert "api.anthropic.com" in _known_provider_hosts()


def _sse(*events):
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)


def test_sdk_request_and_stream_parsing_end_to_end():
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx2")
    from isycode.anthropic_provider import anthropic_stream_complete

    seen = {}
    body = _sse(
        {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant",
                                              "model": "claude-opus-5-5", "content": [],
                                              "stop_reason": None, "stop_sequence": None,
                                              "usage": {"input_tokens": 5, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Plan"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig1"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "toolu_1", "name": "workspace_read", "input": {}}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": "{\"path\": \"app.py\"}"}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
         "usage": {"output_tokens": 20}},
        {"type": "message_stop"},
    )

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    client = anthropic.AsyncAnthropic(
        api_key="test-not-real", http_client=anthropic.DefaultAsyncHttpxClient(
            transport=httpx.MockTransport(handler)))
    chunks = []
    result = asyncio.run(anthropic_stream_complete(
        "test-not-real", "claude-opus-5-5",
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "read app.py"}],
        max_tokens=8192, effort="medium", on_chunk=lambda kind, text: chunks.append((kind, text)),
        tools=[{"type": "function", "function": {"name": "workspace_read", "description": "r",
                                                 "parameters": {"type": "object"}}}],
        client=client))
    sent = seen["body"]
    assert sent["model"] == "claude-opus-5-5" and sent["max_tokens"] == 32000
    assert sent["system"] == "sys" and sent["fallbacks"] == "default"
    assert sent["thinking"]["block_binding"]["prefix_mismatch_behavior"] == "drop_block"
    assert sent["tools"][0]["eager_input_streaming"] is True
    betas = seen["headers"]["anthropic-beta"]
    assert THINKING_BINDING_BETA in betas and FALLBACK_BETA in betas
    assert ("reasoning", "Plan") in chunks
    assert result["tool_calls"][0]["id"] == "toolu_1"
    assert json.loads(result["tool_calls"][0]["function"]["arguments"]) == {"path": "app.py"}
    thinking = result["anthropic_content"][0]
    assert thinking["type"] == "thinking" and thinking["signature"] == "sig1"
