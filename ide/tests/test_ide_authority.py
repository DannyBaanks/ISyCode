"""Behavioral checks for the IDE's new host authority and durable proposals."""

import asyncio
from dataclasses import replace

import pytest

from core.command_grants import CommandIdentity, GrantStore
from core.conversations import ConversationStore
from core.policy import PolicyEngine
from core.proposals import ProposalError, ProposalService
from core.runtime import RuntimeRegistry
from core.runtime.base import ToolCall
from core.tool_execution import ToolExecutionService


def service(root):
    return ToolExecutionService(root, PolicyEngine(), RuntimeRegistry(root))


def test_command_grant_requires_exact_identity_and_can_be_revoked(tmp_path):
    identity = CommandIdentity(str(tmp_path), "/usr/bin/python3", "a" * 64,
                               ("python3", "-m", "pytest"), ".", "b" * 64)
    store = GrantStore(tmp_path)
    store.allow(identity)
    assert store.allowed(identity)
    for altered in [replace(identity, argv=("python3", "-c", "pass")),
                    replace(identity, cwd="tests"), replace(identity, executable_sha256="c" * 64),
                    replace(identity, profile="d" * 64)]:
        assert not store.allowed(altered)
    store.revoke(identity.key)
    assert not store.allowed(identity)
    assert store.list()[0]["enabled"] is False


def test_plan_denies_commands_before_approval(tmp_path):
    host = service(tmp_path)
    invoked = []
    async def approve(call):
        invoked.append(call)
        return True
    result = asyncio.run(host.execute(ToolCall("run_command", {"argv": ["true"]}, "x"), mode="plan", approve=approve))
    assert result.error_code == "PLAN_MODE_WRITE_DENIED"
    assert invoked == []


def test_changing_preview_arguments_cannot_change_applied_content(tmp_path):
    host = service(tmp_path)
    path = tmp_path / "code.py"
    path.write_text("old\n")
    async def approve(call):
        call.arguments["content"] = "unreviewed\n"
        assert "reviewed" in call.prepared_diff
        return True
    result = asyncio.run(host.execute(ToolCall("write", {"path": "code.py", "content": "reviewed\n"}, "x"), mode="coder", approve=approve))
    assert result.success
    assert path.read_text() == "reviewed\n"


def test_disabling_write_while_waiting_blocks_application(tmp_path):
    host = service(tmp_path)
    path = tmp_path / "code.py"
    path.write_text("old\n")
    async def approve(call):
        host.settings.set_enabled("write", False)
        return True
    result = asyncio.run(host.execute(ToolCall("write", {"path": "code.py", "content": "new\n"}, "x"), mode="coder", approve=approve))
    assert result.error_code == "TOOL_DISABLED"
    assert path.read_text() == "old\n"
    assert host.proposals.list()[0]["status"] == "blocked"


def test_batch_with_changed_base_writes_nothing(tmp_path):
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    host = ProposalService(tmp_path)
    batch = host.prepare_batch({"a.py": "new a", "b.py": "new b"})
    (tmp_path / "b.py").write_text("external")
    with pytest.raises(ProposalError, match="STALE_CHANGESET"):
        host.apply_batch(batch)
    assert (tmp_path / "a.py").read_text() == "a"
    assert (tmp_path / "b.py").read_text() == "external"
    assert host.inspect(batch.id)["status"] == "stale"


def test_partial_batch_journals_and_prepares_reviewed_recovery(tmp_path, monkeypatch):
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("old " + name)
    host = ProposalService(tmp_path)
    batch = host.prepare_batch({"a.py": "new a", "created.py": "new file", "b.py": "new b"})
    original = host.apply
    def fail_second_existing(proposal, **kwargs):
        if proposal.path == "b.py":
            raise OSError("injected filesystem failure")
        return original(proposal, **kwargs)
    monkeypatch.setattr(host, "apply", fail_second_existing)
    with pytest.raises(OSError):
        host.apply_batch(batch)
    record = host.inspect(batch.id)
    assert record["status"] == "partial"
    assert len(record["receipts"]) == 2
    recovery, retained = host.prepare_recovery(batch.id)
    assert retained == ["created.py"]
    assert [change.path for change in recovery.changes] == ["a.py"]
    assert (tmp_path / "a.py").read_text() == "new a"
    monkeypatch.setattr(host, "apply", original)
    host.apply_batch(recovery)
    assert (tmp_path / "a.py").read_text() == "old a.py"
    assert (tmp_path / "created.py").read_text() == "new file"


def test_conversation_events_persist_and_active_turn_is_exclusive(tmp_path):
    store = ConversationStore(tmp_path)
    session = store.create()
    turn = store.begin(session, "hello", "demo", "model", "openai")
    store.append_event(session, turn, {"type": "proposal_prepared", "proposal_id": "example"})
    with pytest.raises(ValueError, match="turno activo"):
        store.begin(session, "second", "demo", "model", "openai")
    store.finish(turn, "cancelled")
    reopened = ConversationStore(tmp_path)
    assert reopened.events(session)[0]["payload"]["proposal_id"] == "example"
    assert reopened.turn_status(session) == "cancelled"
