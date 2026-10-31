"""Tests for ISyCode Hive module."""
from __future__ import annotations

from pathlib import Path

from isycode.hive import (
    HiveManager,
    HiveConfig,
    AgentMeta,
    HiveMessage,
    HiveTask,
    MessageAct,
    hive_write_decision,
)
from isycode.hive.guard import HiveWriteInput
from temp_tree import temporary_tree


def test_hive_bootstrap_creates_skeleton():
    with temporary_tree() as tmp:
        config = HiveConfig(harness_home=Path(tmp))
        mgr = HiveManager(config)
        mgr.ensure_hive()

        # Check skeleton
        assert (Path(tmp) / "hive" / "PROTOCOL.md").exists()
        assert (Path(tmp) / "hive" / "registry.json").exists()
        assert (Path(tmp) / "hive" / "board.md").exists()
        assert (Path(tmp) / "hive" / "tasks.json").exists()
        assert (Path(tmp) / "hive" / "log.jsonl").exists()
        assert (Path(tmp) / "hive" / "agents").is_dir()
        assert (Path(tmp) / "hive" / ".git").is_dir()


def test_agent_upsert_and_registry():
    with temporary_tree() as tmp:
        config = HiveConfig(harness_home=Path(tmp))
        mgr = HiveManager(config)
        mgr.ensure_hive()

        agent = mgr.upsert_agent(AgentMeta(
            id="test-agent",
            name="Test Agent",
            provider="claude",
            role="worker",
            cwd=tmp,
        ))

        assert agent.id == "test-agent"
        assert agent.cwd_valid is True
        assert agent.status == "idle"

        # Registry persistence
        assert "test-agent" in mgr.registry.agents
        assert mgr.registry.agents["test-agent"].name == "Test Agent"


def test_agent_workspace_created():
    with temporary_tree() as tmp:
        config = HiveConfig(harness_home=Path(tmp))
        mgr = HiveManager(config)
        mgr.ensure_hive()

        mgr.upsert_agent(AgentMeta(id="test-agent", name="Test", provider="claude", cwd=tmp))

        agent_dir = Path(tmp) / "hive" / "agents" / "test-agent"
        assert agent_dir.exists()
        assert (agent_dir / "identity.md").exists()
        assert (agent_dir / "memory.md").exists()
        assert (agent_dir / "inbox").is_dir()
        assert (agent_dir / "inbox" / ".done").is_dir()
        assert (agent_dir / "outbox").is_dir()
        assert (agent_dir / "outbox" / ".sent").is_dir()
        assert (agent_dir / "cursor.json").exists()


def test_message_send_and_read():
    with temporary_tree() as tmp:
        config = HiveConfig(harness_home=Path(tmp))
        mgr = HiveManager(config)
        mgr.ensure_hive()

        mgr.upsert_agent(AgentMeta(id="alice", name="Alice", provider="claude", cwd=tmp))
        mgr.upsert_agent(AgentMeta(id="bob", name="Bob", provider="claude", cwd=tmp))

        msg = mgr.send_message(
            from_agent="alice",
            to_agent="bob",
            act=MessageAct.REQUEST,
            subject="Hello",
            body="Please do the thing",
        )

        assert msg.id.startswith("msg-")
        assert msg.from_agent == "alice"
        assert msg.to_agent == "bob"
        assert msg.act == MessageAct.REQUEST

        # Message is in sender's outbox (router delivers to recipient's inbox)
        outbox = mgr.read_outbox("alice")
        assert len(outbox) == 1
        assert outbox[0].id == msg.id


def test_task_crud():
    with temporary_tree() as tmp:
        config = HiveConfig(harness_home=Path(tmp))
        mgr = HiveManager(config)
        mgr.ensure_hive()

        mgr.upsert_agent(AgentMeta(id="worker", name="Worker", provider="claude", cwd=tmp))

        task = mgr.create_task(
            title="Fix the bug",
            description="Details here",
            assignee="worker",
            priority=5,
        )

        assert task.id.startswith("task-")
        assert task.title == "Fix the bug"
        assert task.assignee == "worker"
        assert task.status == "todo"

        # List tasks
        tasks = mgr.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == task.id

        # Update task
        updated = mgr.update_task(task.id, status="doing")
        assert updated is not None
        assert updated.status == "doing"


def test_write_guard_allows_own_files():
    with temporary_tree() as tmp:
        config = HiveConfig(harness_home=Path(tmp))
        mgr = HiveManager(config)
        mgr.ensure_hive()
        mgr.upsert_agent(AgentMeta(id="agent1", name="Agent 1", provider="claude", cwd=tmp))

        # Write to own memory.md
        decision = mgr.check_write(
            tool="Write",
            tool_input={"file_path": str(Path(tmp) / "hive" / "agents" / "agent1" / "memory.md")},
            cwd=tmp,
            agent_id="agent1",
        )
        assert decision["deny"] is False

        # Write to own outbox
        decision = mgr.check_write(
            tool="Write",
            tool_input={"file_path": str(Path(tmp) / "hive" / "agents" / "agent1" / "outbox" / "msg.json")},
            cwd=tmp,
            agent_id="agent1",
        )
        assert decision["deny"] is False

        # Write to tasks.json
        decision = mgr.check_write(
            tool="Write",
            tool_input={"file_path": str(Path(tmp) / "hive" / "tasks.json")},
            cwd=tmp,
            agent_id="agent1",
        )
        assert decision["deny"] is False


def test_write_guard_denies_other_agent_files():
    with temporary_tree() as tmp:
        config = HiveConfig(harness_home=Path(tmp))
        mgr = HiveManager(config)
        mgr.ensure_hive()
        mgr.upsert_agent(AgentMeta(id="agent1", name="Agent 1", provider="claude", cwd=tmp))
        mgr.upsert_agent(AgentMeta(id="agent2", name="Agent 2", provider="claude", cwd=tmp))

        # Agent1 tries to write to agent2's memory
        decision = mgr.check_write(
            tool="Write",
            tool_input={"file_path": str(Path(tmp) / "hive" / "agents" / "agent2" / "memory.md")},
            cwd=tmp,
            agent_id="agent1",
        )
        assert decision["deny"] is True
        assert "hive folder is only for coordination" in decision["reason"]


def test_write_guard_god_can_write_board():
    with temporary_tree() as tmp:
        config = HiveConfig(harness_home=Path(tmp))
        mgr = HiveManager(config)
        mgr.ensure_hive()
        mgr.upsert_agent(AgentMeta(id="god", name="God", provider="claude", cwd=tmp, is_god=True))

        decision = mgr.check_write(
            tool="Write",
            tool_input={"file_path": str(Path(tmp) / "hive" / "board.md")},
            cwd=tmp,
            agent_id="god",
        )
        assert decision["deny"] is False


def test_hive_message_serialization():
    msg = HiveMessage(
        id="msg-test",
        conversation="conv-1",
        in_reply_to=None,
        from_agent="alice",
        to_agent="bob",
        act=MessageAct.PROPOSE,
        subject="Plan",
        body="Let's do X",
    )

    jsonl = msg.to_jsonl()
    parsed = HiveMessage.from_jsonl(jsonl)

    assert parsed.id == msg.id
    assert parsed.from_agent == msg.from_agent
    assert parsed.to_agent == msg.to_agent
    assert parsed.act == msg.act


def test_hive_task_serialization():
    task = HiveTask(
        id="task-1",
        title="Test",
        assignee="agent1",
        status="doing",
    )

    d = task.to_dict()
    assert d["id"] == "task-1"
    assert d["title"] == "Test"
    assert d["assignee"] == "agent1"
    assert d["status"] == "doing"
    assert d["dependsOn"] == []

    parsed = HiveTask.from_dict(d)
    assert parsed.id == task.id
    assert parsed.title == task.title
    assert parsed.assignee == task.assignee
    assert parsed.status == task.status