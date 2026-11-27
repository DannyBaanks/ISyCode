"""UI bridge tests: ObservableAgent must observe, never change behavior.

These tests run the REAL Agent loop (core/agent/run.py) with a stub
provider so no network is touched. They prove:
  - ObservableAgent subclasses Agent and does NOT duplicate run()
  - tool_call / tool_result events are emitted around the real
    policy -> runtime -> verify pipeline
  - policy decisions (PLAN mode deny) still come from core
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.agent import (Agent, AgentContext, ProviderRegistry, PolicyEngine,
                        RuntimeRegistry, SecretBroker)
from core.agent.providers.base import (BaseProvider, CompletionResponse,
                                       ToolCall as ProviderToolCall)
from ui.bridge import ObservableAgent


class StubProvider(BaseProvider):
    def __init__(self, responses):
        self._responses = list(responses)

    async def complete(self, messages, tools=None):
        return self._responses.pop(0)

    async def stream(self, messages, tools=None):
        yield ""

    async def close(self):
        pass


def make_agent(tmp_path, responses, mode="coder", on_event=None):
    registry = ProviderRegistry(SecretBroker(), config_path=tmp_path / "config.yaml")
    policy = PolicyEngine()
    runtime = RuntimeRegistry(tmp_path)
    context = AgentContext(
        provider_name="stub",
        model="stub-model",
        system_prompt="test",
        working_dir=str(tmp_path),
        max_turns=5,
        mode=mode,
        plan_context=None,
    )
    agent = ObservableAgent(context, registry, policy, runtime, SecretBroker(),
                            resident_recorder=None, on_event=on_event)
    agent.provider = StubProvider(responses)
    return agent


def collect_events(agent, prompt):
    events = []
    agent._on_event = events.append

    async def run():
        async for _chunk in agent.run(prompt):
            pass
    asyncio.run(run())
    return events


def test_observable_agent_is_real_agent_subclass():
    assert issubclass(ObservableAgent, Agent)


def test_observable_agent_does_not_duplicate_run():
    # run() must be the inherited loop: if this fails, the class is
    # re-implementing the loop and the acceptance rule is violated.
    assert ObservableAgent.run is Agent.run


def test_tool_call_and_result_events_emitted(tmp_path):
    events = []
    responses = [
        CompletionResponse(
            content="listing files",
            tool_calls=[ProviderToolCall(id="t1", name="glob",
                                         arguments={"pattern": "*.py"})],
        ),
        CompletionResponse(content="done", finish_reason="stop"),
    ]
    agent = make_agent(tmp_path, responses, on_event=events.append)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    events = collect_events(agent, "list files")

    calls = [e for e in events if e["type"] == "tool_call"]
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(calls) == 1
    assert calls[0]["tool"] == "glob"
    assert calls[0]["arguments"] == {"pattern": "*.py"}
    assert len(results) == 1
    assert results[0]["tool"] == "glob"
    assert results[0]["success"] is True
    assert "a.py" in results[0]["stdout"]


def test_policy_plan_mode_deny_is_preserved(tmp_path):
    events = []
    responses = [
        CompletionResponse(
            content="",
            tool_calls=[ProviderToolCall(id="t1", name="write",
                                         arguments={"path": "out.txt",
                                                    "content": "hi"})],
        ),
        CompletionResponse(content="done", finish_reason="stop"),
    ]
    agent = make_agent(tmp_path, responses, mode="plan", on_event=events.append)
    events = collect_events(agent, "write a file")

    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == 1
    assert results[0]["success"] is False
    assert results[0]["error_code"] == "PLAN_MODE_WRITE_DENIED"
    assert not (tmp_path / "out.txt").exists()


def test_evidence_actor_attached_by_core(tmp_path):
    events = []
    responses = [
        CompletionResponse(
            content="",
            tool_calls=[ProviderToolCall(id="t1", name="glob",
                                         arguments={"pattern": "*"})],
        ),
        CompletionResponse(content="done", finish_reason="stop"),
    ]
    agent = make_agent(tmp_path, responses, mode="coder", on_event=events.append)
    events = collect_events(agent, "look")

    results = [e for e in events if e["type"] == "tool_result"]
    evidence = results[0]["evidence"]
    assert evidence["actor"] == "AGENT"
    assert evidence["policy"]["mode"] == "coder"
    assert evidence["policy"]["runtime"] == "layer_a"