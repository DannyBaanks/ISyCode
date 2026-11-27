"""Focused unit tests for swarm2 core safety & reliability fixes (P0/P1 EGM audit)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from core.agent.chat import IsycoAgentApp
from core.agent.providers import ProviderConfig, ProviderRegistry
from core.agent.providers.base import BaseProvider, CompletionResponse, ToolCall
from core.agent.providers.google import GoogleProvider
from core.agent.run import Agent, AgentContext
from core.conversations import ConversationStore
from core.policy import ActionType, PolicyEngine, PolicyRule, RuntimeLayer, _eval_policy_condition
from core.runtime import RuntimeRegistry
from core.secret_broker import SecretBroker
from ui.thread import AgentWorker, HostToolWorker


# ---------------------------------------------------------------------------
# 1. core/policy.py — safe AST evaluator (zero eval/exec)
# ---------------------------------------------------------------------------

def test_policy_source_contains_no_eval_or_exec():
    src = Path(__file__).resolve().parent.parent.joinpath("core", "policy.py").read_text(encoding="utf-8")
    assert "eval(" not in src
    assert "exec(" not in src


def test_policy_default_rules_and_declarative_conditions():
    engine = PolicyEngine()

    # Network always denied
    net = engine.evaluate("network", "https://example.com", {})
    assert net.allowed is False
    assert net.runtime == RuntimeLayer.LAYER_A

    # Isolated linux takes precedence over untrusted/trusted
    iso = engine.evaluate("execute", "pytest", {"isolated_linux": True, "trusted": True})
    assert iso.allowed is True
    assert iso.runtime == RuntimeLayer.LINUX_ISOLATED

    # Untrusted execute -> Layer B
    untrusted = engine.evaluate("execute", "bash", {"trusted": False})
    assert untrusted.allowed is True
    assert untrusted.runtime == RuntimeLayer.LAYER_B

    # Trusted execute -> Layer A
    trusted = engine.evaluate("execute", "python", {"trusted": True})
    assert trusted.allowed is True
    assert trusted.runtime == RuntimeLayer.LAYER_A

    # Compound boolean, comparisons, literals, resource predicates
    assert _eval_policy_condition(
        "context.get('level', 0) >= 2 and not context.get('blocked', False)",
        {"level": 3},
        "app.py",
    ) is True
    assert _eval_policy_condition(
        "context.get('role') in ('admin', 'ops') or resource.endswith('.py')",
        {"role": "guest"},
        "app.py",
    ) is True
    assert _eval_policy_condition(
        "context.get('role') == 'admin' and resource.startswith('src/')",
        {"role": "admin"},
        "tests/test.py",
    ) is False


@pytest.mark.parametrize(
    "malicious",
    [
        "__import__('os').system('echo pwned')",
        "(lambda: True)()",
        "().__class__.__bases__[0].__subclasses__()",
        "open('/etc/passwd')",
        "context.__class__",
        "context.pop('trusted', True)",
        "1 + 1",
    ],
)
def test_policy_rejects_code_injection_and_defaults_to_deny(malicious):
    with pytest.raises(ValueError):
        _eval_policy_condition(malicious, {"trusted": True}, "file.py")

    engine = PolicyEngine([
        PolicyRule(
            action=ActionType.EXECUTE,
            condition=malicious,
            runtime=RuntimeLayer.LAYER_A,
            allowed=True,
            reason="should never match",
        )
    ])
    decision = engine.evaluate("execute", "file.py", {"trusted": True})
    assert decision.allowed is False
    assert "No matching rule" in decision.reason


# ---------------------------------------------------------------------------
# 2. core/conversations.py — SQLite WAL mode + busy_timeout=5000
# ---------------------------------------------------------------------------

def test_conversation_store_enables_wal_and_busy_timeout(tmp_path):
    store = ConversationStore(tmp_path)
    session = store.create(title="WAL test", provider="openai", model="gpt-4o", protocol="openai")
    assert session

    with store._connection() as db:
        journal_mode = db.execute("PRAGMA journal_mode;").fetchone()[0]
        busy_timeout = db.execute("PRAGMA busy_timeout;").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_keys;").fetchone()[0]

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) == 5000
    assert int(foreign_keys) == 1

    # Verify reader does not contend with an open writer transaction in WAL mode
    writer = sqlite3.connect(store.path, timeout=5)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            ("s2", "concurrent", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "openai", "gpt-4o", "openai"),
        )
        # Store read succeeds while writer holds an uncommitted write transaction
        sessions = store.list()
        assert any(item["id"] == session for item in sessions)
        writer.rollback()
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# Helpers for Agent loop tests (P0-2, P0-3, P0-4)
# ---------------------------------------------------------------------------

class _SequenceProvider(BaseProvider):
    def __init__(self, responses, provider_type="openai"):
        super().__init__(
            ProviderConfig("mock", provider_type, "mock-model", "http://mock"),
            SecretBroker(),
        )
        self._responses = list(responses)
        self.seen_messages: list[list[dict]] = []
        self.seen_tool_results: list[list[dict]] = []

    async def complete(self, messages, tools=None):
        self.seen_messages.append(json.loads(json.dumps(messages)))
        if not self._responses:
            raise AssertionError("Provider called more times than expected")
        return self._responses.pop(0)

    async def stream(self, messages, tools=None):
        yield ""

    def build_tool_messages(self, response, results):
        self.seen_tool_results.append(json.loads(json.dumps(results)))
        return super().build_tool_messages(response, results)

    async def close(self):
        pass


def _make_agent(tmp_path, provider, *, max_turns=5, history=None, mode="coder"):
    registry = ProviderRegistry(SecretBroker(), config_path=tmp_path / "config.yaml")
    registry.add("mock", provider.config.provider_type, "mock-model")
    registry.from_config = lambda config: provider
    ctx = AgentContext(
        provider_name="mock",
        model="mock-model",
        system_prompt="test",
        working_dir=str(tmp_path),
        max_turns=max_turns,
        mode=mode,
    )
    if history is not None:
        ctx.history = history
    return Agent(
        ctx,
        registry,
        PolicyEngine(),
        RuntimeRegistry(tmp_path),
        registry.secret_broker,
        on_approval=lambda call: asyncio.sleep(0, result=True),
    )


async def _collect(stream):
    return "".join([chunk async for chunk in stream])


# ---------------------------------------------------------------------------
# 3. P0-2: /resume never sets context.history = None & Agent guards None history
# ---------------------------------------------------------------------------

def test_resume_conversation_keeps_history_as_list_and_agent_guards_none(tmp_path):
    store = ConversationStore(tmp_path)
    session = store.create(title="Saved", provider="mock", model="m", protocol="openai")

    async def run_tui():
        app = IsycoAgentApp(working_dir=str(tmp_path))
        async with app.run_test():
            await app.handle_command("/resume " + session)
            assert app.context.history == []
            assert isinstance(app.context.history, list)

    asyncio.run(run_tui())

    # Even if a caller forces ctx.history = None directly, Agent must not crash
    provider = _SequenceProvider([CompletionResponse("ok", None, "stop")])
    agent = _make_agent(tmp_path, provider)
    agent.ctx.history = None
    out = asyncio.run(_collect(agent.run("hello")))
    assert out == "ok"
    assert agent.messages[0]["role"] == "system"
    assert agent.messages[1] == {"role": "user", "content": "hello"}


# ---------------------------------------------------------------------------
# 4. P0-3: Strict max_turns enforcement inside tool-execution loop
# ---------------------------------------------------------------------------

def test_max_turns_strictly_prevents_extra_tool_rounds(tmp_path):
    # With max_turns=1, a tool_call on turn 0 must NOT dispatch any tool round
    provider_1 = _SequenceProvider([
        CompletionResponse(
            "trying tool",
            [ToolCall("tc-1", "write", {"path": "should_not_exist.txt", "content": "nope"})],
            "tool_calls",
        ),
    ])
    agent_1 = _make_agent(tmp_path, provider_1, max_turns=1)
    out_1 = asyncio.run(_collect(agent_1.run("do work")))
    assert "Max turns reached" in out_1
    assert len(provider_1.seen_messages) == 1
    assert not (tmp_path / "should_not_exist.txt").exists()

    # With max_turns=2, turn 0 executes its tool round; turn 1 tool_call is blocked before dispatch
    provider_2 = _SequenceProvider([
        CompletionResponse(
            "first write",
            [ToolCall("tc-1", "write", {"path": "allowed.txt", "content": "ok"})],
            "tool_calls",
        ),
        CompletionResponse(
            "second write beyond max_turns",
            [ToolCall("tc-2", "write", {"path": "blocked.txt", "content": "no"})],
            "tool_calls",
        ),
    ])
    agent_2 = _make_agent(tmp_path, provider_2, max_turns=2)
    out_2 = asyncio.run(_collect(agent_2.run("do two writes")))
    assert "Max turns reached" in out_2
    assert len(provider_2.seen_messages) == 2
    assert (tmp_path / "allowed.txt").exists()
    assert not (tmp_path / "blocked.txt").exists()


# ---------------------------------------------------------------------------
# 5. P0-4: Tool-result messages include tool `name` in history
# ---------------------------------------------------------------------------

def test_tool_result_messages_include_tool_name_in_history(tmp_path):
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    provider = _SequenceProvider([
        CompletionResponse(
            "reading",
            [ToolCall("call-read-1", "read", {"path": "hello.txt"})],
            "tool_calls",
        ),
        CompletionResponse("done", None, "stop"),
    ])
    agent = _make_agent(tmp_path, provider, max_turns=4)
    out = asyncio.run(_collect(agent.run("read hello.txt")))
    assert "done" in out

    # Passed to build_tool_messages with `name`
    assert provider.seen_tool_results[0][0]["name"] == "read"
    assert provider.seen_tool_results[0][0]["tool_call_id"] == "call-read-1"

    # Stored in agent.messages and sent to provider on next turn with `name`
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["name"] == "read"
    assert tool_msgs[0]["tool_call_id"] == "call-read-1"

    sent_tool_msgs = [m for m in provider.seen_messages[1] if m.get("role") == "tool"]
    assert len(sent_tool_msgs) == 1
    assert sent_tool_msgs[0]["name"] == "read"

    # Also verify GoogleProvider pairing succeeds end-to-end with tool_results containing `name`
    google = GoogleProvider(
        ProviderConfig("google", "google", "gemini-2.5-pro", "https://fixture/v1beta"),
        SecretBroker(),
    )
    resp = CompletionResponse("checking", [ToolCall("g-1", "read", {"path": "hello.txt"})], "STOP")
    wire = google.build_tool_messages(resp, [{"tool_call_id": "g-1", "name": "read", "content": "{}"}])
    payload = google._payload(wire, None)
    assert payload["contents"][1]["parts"][0]["functionResponse"]["name"] == "read"
    asyncio.run(google.close())


# ---------------------------------------------------------------------------
# 6. P1-4: ui/thread.py approval bridge thread-safety & race handling
# ---------------------------------------------------------------------------

def test_resolve_approval_handles_closed_loop_cancelled_and_missing_safely(qapp):
    worker = HostToolWorker(lambda approve: asyncio.sleep(0))

    # No loop yet
    assert worker.resolve_approval("missing", True) is False

    # Closed loop
    closed_loop = asyncio.new_event_loop()
    fut = closed_loop.create_future()
    closed_loop.close()
    worker._loop = closed_loop
    worker._pending_approvals["a1"] = fut
    assert worker.resolve_approval("a1", True) is False

    # Already-cancelled future on an open loop
    open_loop = asyncio.new_event_loop()
    try:
        cancelled_fut = open_loop.create_future()
        cancelled_fut.cancel()
        worker._loop = open_loop
        worker._pending_approvals["a2"] = cancelled_fut
        assert worker.resolve_approval("a2", True) is False

        # Cancelled worker ignores late resolve_approval
        pending_fut = open_loop.create_future()
        worker._pending_approvals["a3"] = pending_fut
        worker._cancelled = True
        assert worker.resolve_approval("a3", True) is False
    finally:
        open_loop.close()


def test_host_tool_worker_approval_bridge_concurrent_resolve_and_cancel(qapp):

    # Case A: Normal cross-thread resolution succeeds cleanly
    approved_results = []
    approval_ready = threading.Event()
    captured_id = []

    async def op_approve(approve):
        call = SimpleNamespace(name="write", arguments={"path": "a.py"}, prepared_diff="+x")
        ans = await approve(call)
        approved_results.append(ans)
        return ans

    worker = HostToolWorker(op_approve)

    def on_requested(aid, tool_name, args, diff):
        captured_id.append(aid)
        approval_ready.set()

    worker.approval_requested.connect(on_requested, Qt.ConnectionType.DirectConnection)
    t = threading.Thread(target=worker.run, daemon=True)
    t.start()
    assert approval_ready.wait(timeout=3.0)
    assert worker.resolve_approval(captured_id[0], True) is True
    t.join(timeout=3.0)
    assert not t.is_alive()
    assert approved_results == [True]
    # Late resolution after completion is a safe no-op
    assert worker.resolve_approval(captured_id[0], False) is False

    # Case B: Concurrent cancel + resolve_approval during shutdown must never raise
    errors = []
    for _ in range(15):
        ready = threading.Event()
        aid_holder = []

        async def op_wait(approve):
            call = SimpleNamespace(name="write", arguments={"path": "b.py"}, prepared_diff="+y")
            return await approve(call)

        w = HostToolWorker(op_wait)

        def on_req(aid, tool_name, args, diff, _r=ready, _h=aid_holder):
            _h.append(aid)
            _r.set()

        w.approval_requested.connect(on_req, Qt.ConnectionType.DirectConnection)
        wt = threading.Thread(target=w.run, daemon=True)
        wt.start()
        assert ready.wait(timeout=3.0)

        def spam_resolve(_w=w, _aid=aid_holder[0]):
            try:
                for _ in range(20):
                    _w.resolve_approval(_aid, True)
            except Exception as exc:
                errors.append(exc)

        rt = threading.Thread(target=spam_resolve, daemon=True)
        rt.start()
        w.cancel()
        rt.join(timeout=3.0)
        wt.join(timeout=3.0)
        assert not wt.is_alive()
        assert w._pending_approvals == {}

    assert errors == []

    # Case C: Verify AgentWorker shares the same lock-guarded resolve_approval/cancel
    assert hasattr(AgentWorker, "resolve_approval")
    assert HostToolWorker.resolve_approval is AgentWorker.resolve_approval
    assert HostToolWorker.cancel is AgentWorker.cancel
