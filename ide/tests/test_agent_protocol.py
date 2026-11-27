import asyncio
import json

from core.agent.providers import ProviderConfig, ProviderRegistry
from core.agent.providers.base import BaseProvider, CompletionResponse, ToolCall
from core.agent.run import Agent, AgentContext
from core.policy import ActionType, PolicyEngine, PolicyRule, RuntimeLayer
from core.runtime import RuntimeRegistry
from core.resident import ResidentReader, ResidentRecorder
from core.secret_broker import SecretBroker


class StrictProtocolProvider(BaseProvider):
    def __init__(self, config, broker, sequence):
        super().__init__(config, broker)
        self.sequence = sequence
        self.calls = []

    async def complete(self, messages, tools=None):
        self.calls.append(json.loads(json.dumps(messages)))
        return self.sequence[len(self.calls) - 1]

    async def stream(self, messages, tools=None):
        yield ""


def make_agent(tmp_path, provider, recorder=None):
    registry = ProviderRegistry(SecretBroker(), config_path=tmp_path / "config.yaml")
    registry.add("mock", "openai", "mock-model")
    registry.from_config = lambda config: provider
    return Agent(
        AgentContext("mock", "mock-model", "test", str(tmp_path), max_turns=8, mode="coder"),
        registry,
        PolicyEngine(),
        RuntimeRegistry(tmp_path),
        registry.secret_broker,
        recorder, on_approval=lambda call: asyncio.sleep(0, result=True),
    )


def test_assistant_tool_calls_and_multiple_results_are_preserved(tmp_path):
    provider = StrictProtocolProvider(
        ProviderConfig("mock", "openai", "mock-model", "http://mock"),
        SecretBroker(),
        [
            CompletionResponse(
                "checking",
                [
                    ToolCall("write-1", "write", {"path": "ok.py", "content": "ok"}),
                    ToolCall("missing-1", "read", {"path": "missing.py"}),
                ],
                "tool_calls",
            ),
            CompletionResponse("done", None, "stop"),
        ],
    )
    agent = make_agent(tmp_path, provider)
    asyncio.run(_collect(agent.run("do it")))

    assert len(provider.calls) == 2
    assistant = provider.calls[1][-3]
    tools = provider.calls[1][-2:]
    assert assistant["role"] == "assistant"
    assert [c["id"] for c in assistant["tool_calls"]] == ["write-1", "missing-1"]
    assert [m["tool_call_id"] for m in tools] == ["write-1", "missing-1"]
    assert json.loads(tools[1]["content"])["error_code"] == "FILE_NOT_FOUND"


def test_read_write_read_verify_e2e(tmp_path):
    (tmp_path / "hello.py").write_text('def hello():\n    return "hello"\n', encoding="utf-8")
    provider = StrictProtocolProvider(
        ProviderConfig("mock", "openai", "mock-model", "http://mock"),
        SecretBroker(),
        [
            CompletionResponse("read", [ToolCall("read-1", "read", {"path": "hello.py"})], "tool_calls"),
            CompletionResponse("write", [ToolCall("write-1", "write", {"path": "hello.py", "content": 'def hello():\n    return "hello from ISyCo"\n'})], "tool_calls"),
            CompletionResponse("read back", [ToolCall("read-2", "read", {"path": "hello.py"})], "tool_calls"),
            CompletionResponse("verify", [ToolCall("verify-1", "verify", {"target": "hello.py"})], "tool_calls"),
            CompletionResponse("DONE", None, "stop"),
        ],
    )
    recorder = ResidentRecorder(tmp_path)
    agent = make_agent(tmp_path, provider, recorder)
    output = asyncio.run(_collect(agent.run("modify hello")))

    assert output.endswith("DONE")
    assert 'hello from ISyCo' in (tmp_path / "hello.py").read_text(encoding="utf-8")
    assert len(provider.calls) == 5
    final_tool_result = provider.calls[4 - 0][-1]
    assert final_tool_result["role"] == "tool"
    assert "verification" in json.loads(final_tool_result["content"])["evidence"]
    resident_changes = ResidentReader(tmp_path)._records("changes.jsonl")
    assert {item["type"] for item in resident_changes} == {"change", "verification"}
    session_records = ResidentReader(tmp_path)._records("sessions" + "/" + agent.session_id + ".jsonl")
    assert session_records[0]["event"] == "started"
    assert session_records[-1]["event"] == "ended"


def test_unavailable_layer_is_structured_error(tmp_path):
    provider = StrictProtocolProvider(
        ProviderConfig("mock", "openai", "mock-model", "http://mock"),
        SecretBroker(),
        [],
    )
    agent = make_agent(tmp_path, provider)
    agent.policy = PolicyEngine([
        PolicyRule(
            action=ActionType.EXECUTE,
            condition="True",
            runtime=RuntimeLayer.LAYER_B,
            reason="test requires unavailable Layer B",
        )
    ])
    result = asyncio.run(agent._execute_tool(ToolCall("layer-b", "python", {"code": "1 + 1"})))
    assert not result.success
    assert result.error_code == "UNAVAILABLE_TOOL"


async def _collect(stream):
    return "".join([chunk async for chunk in stream])
