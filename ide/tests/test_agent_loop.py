"""Test the agent loop with a fake provider."""

import asyncio
import sys
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent.run import Agent, AgentContext, AVAILABLE_TOOLS
from core.agent.providers import ProviderRegistry, ProviderConfig
from core.agent.providers.base import BaseProvider, CompletionResponse, ToolCall
from core.policy import PolicyEngine
from core.runtime import RuntimeRegistry
from core.secret_broker import SecretBroker


class MockProvider(BaseProvider):
    """Fake provider: returns a tool call first, then a final answer."""
    
    def __init__(self, config, secret_broker):
        super().__init__(config, secret_broker)
        self.calls = 0
    
    async def complete(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return CompletionResponse(
                content="Let me check that file.",
                tool_calls=[
                    ToolCall(id="call_1", name="write", arguments={
                        "path": "hello.txt",
                        "content": "Hello from IsyVM agent!"
                    })
                ],
                finish_reason="tool_calls"
            )
        elif self.calls == 2:
            return CompletionResponse(
                content="I wrote the file. Let me read it back.",
                tool_calls=[
                    ToolCall(id="call_2", name="read", arguments={"path": "hello.txt"})
                ],
                finish_reason="tool_calls"
            )
        else:
            return CompletionResponse(
                content="Done! The file was created successfully.",
                finish_reason="stop"
            )
    
    async def stream(self, messages, tools=None):
        yield "mock"


async def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    
    secret_broker = SecretBroker()
    provider_registry = ProviderRegistry(secret_broker, config_path=tmp / "config.yaml")
    provider_registry.add("mock", "openai", "mock-model")
    # Override with mock provider
    mock = MockProvider(ProviderConfig(
        name="mock", provider_type="openai", model="mock-model", endpoint="http://mock"
    ), secret_broker)
    provider_registry.from_config = lambda config: mock
    
    policy_engine = PolicyEngine()
    runtime_registry = RuntimeRegistry(tmp)
    
    context = AgentContext(
        provider_name="mock",
        model="mock-model",
        system_prompt="test",
        working_dir=str(tmp),
        max_turns=5, mode="coder"
    )
    
    agent = Agent(context, provider_registry, policy_engine, runtime_registry, secret_broker, on_approval=lambda call: asyncio.sleep(0, result=True))
    
    print("=== Agent run ===")
    async for chunk in agent.run("Create a hello file"):
        print(chunk)
    
    print("\n=== Verification ===")
    created = tmp / "hello.txt"
    print(f"File exists: {created.exists()}")
    if created.exists():
        print(f"Content: {created.read_text(encoding='utf-8')!r}")
    
    print("\n=== Policy check: bash is untrusted ===")
    decision = policy_engine.evaluate("execute", "bash", {"tool": "bash", "trusted": False})
    print(f"bash -> {decision.runtime.value} allowed={decision.allowed} ({decision.reason})")
    
    decision = policy_engine.evaluate("read", "read", {"tool": "read", "trusted": True})
    print(f"read -> {decision.runtime.value} allowed={decision.allowed}")
    
    print("\nALL TESTS PASSED" if created.exists() else "\nFAILED: file not created")


if __name__ == "__main__":
    asyncio.run(main())


def test_agent_loop():
    asyncio.run(main())
