from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.approvals import ActionApprovalStore
from isycode.workspace_authority import OneShotActionAuthority, WorkspaceAuthority
from isycode.workspace_memory import (
    MEMORY_TOOL_OPERATIONS, MemoryStore, WorkspaceMemoryOwner,
)


def test_memory_store_is_private_and_scoped_outside_workspace(tmp_path):
    workspace = tmp_path / "project"
    other_workspace = tmp_path / "other"
    workspace.mkdir()
    other_workspace.mkdir()
    state = tmp_path / "state"
    store = MemoryStore(workspace, state_directory=state)
    other = MemoryStore(other_workspace, state_directory=state)

    assert store.path.is_relative_to(state)
    assert not store.path.is_relative_to(workspace)
    assert store.path != other.path
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store.path.parent.stat().st_mode & 0o777 == 0o700


def test_memory_store_recall_update_consolidate_and_forget(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = MemoryStore(workspace, state_directory=tmp_path / "state")

    first = store.perform("store", {
        "topic": "decisions-demo", "content": "Use SQLite for local memory.",
        "importance": "high", "keywords": ["database", "sqlite"],
    })["id"]
    second = store.perform("store", {
        "topic": "decisions-demo", "content": "Keep SQLite files outside checkouts.",
        "importance": "medium", "keywords": ["storage"],
    })["id"]
    secret = store.perform("store", {
        "topic": "errors-resolved", "content": "api_key=should-not-persist",
        "importance": "low", "keywords": [],
    })["id"]
    assert store.perform("recall", {"query": "should-not-persist"})["count"] == 0
    matches = store.perform("recall", {"query": "SQLite local", "limit": 5})
    assert first in {item["id"] for item in matches["results"]}
    assert store.perform("update", {"id": first, "importance": "critical"})["updated"]
    with pytest.raises(ValueError, match="critical memories"):
        store.perform("consolidate", {
            "topic": "decisions-demo", "ids": [first, second], "summary": "Keep local SQLite."
        })
    store.perform("update", {"id": first, "importance": "high"})
    result = store.perform("consolidate", {
        "topic": "decisions-demo", "ids": [first, second], "summary": "Keep local SQLite."
    })
    assert result["consolidated"] == 2
    assert store.perform("recall", {"query": "SQLite", "topic": "decisions-demo"})["count"] == 1
    assert store.perform("forget", {"id": secret})["forgotten"]
    assert store.perform("list_topics", {})["topics"][0]["topic"] == "decisions-demo"


def test_memoir_graph_and_search_are_workspace_local(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = MemoryStore(workspace, state_directory=tmp_path / "state")
    memoir = store.perform("create_memoir", {
        "name": "Architecture", "description": "Important design concepts."
    })
    concept_a = store.perform("add_concept", {
        "memoir": "architecture", "name": "Workspace authority",
        "definition": "Owns explicit per-workspace grants.", "labels": ["security:policy"],
    })
    concept_b = store.perform("add_concept", {
        "memoir": "Architecture", "name": "Sentinel",
        "definition": "Aggregates read-only checks.", "labels": ["security:policy"],
    })
    store.perform("link_concepts", {
        "memoir": "Architecture", "source_id": concept_a["id"],
        "target_id": concept_b["id"], "relation": "checks",
    })
    assert store.perform("search_memoir", {
        "memoir": "Architecture", "query": "explicit grants"
    })["results"][0]["id"] == concept_a["id"]
    shown = store.perform("show_memoir", {"name": "Architecture"})
    assert shown["memoir"] == memoir["name"]
    assert shown["links"] == [{
        "source_id": concept_a["id"], "target_id": concept_b["id"], "relation": "checks",
    }]


def test_memory_requests_are_bounded_approved_and_journaled(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    state = tmp_path / "state"
    approvals = ActionApprovalStore()
    base = WorkspaceAuthority(workspace, state_directory=state / "authority")
    owner = WorkspaceMemoryOwner(workspace, base, approvals, state_directory=state / "memory")
    preview = owner.prepare("store", {
        "topic": "decisions-demo", "content": "No ICM code is used."
    })
    assert not (state / "memory").exists()
    assert owner.execute(preview).decision == "DENY"

    changed_authority = OneShotActionAuthority(base, preview.request)
    changed_owner = WorkspaceMemoryOwner(
        workspace, changed_authority, approvals, state_directory=state / "memory")
    changed = replace(preview, arguments={**preview.arguments, "content": "changed"})
    assert changed_owner.execute(changed).decision == "DENY"

    authorized = WorkspaceMemoryOwner(
        workspace, OneShotActionAuthority(base, preview.request), approvals,
        state_directory=state / "memory")
    outcome = authorized.execute(preview)
    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    assert ActionAuditJournal(workspace).verify().receipts == 1
    log_text = "".join(path.read_text() for path in
                       (workspace / ".isycode" / "action-journal").glob("*.jsonl"))
    assert "No ICM code is used." not in log_text


def test_tool_map_and_input_validation_reject_operator_and_bad_fields(tmp_path):
    assert MEMORY_TOOL_OPERATIONS["memory_forget"] == "forget"
    workspace = tmp_path / "project"
    workspace.mkdir()
    owner = WorkspaceMemoryOwner(
        workspace, WorkspaceAuthority(workspace, state_directory=tmp_path / "authority"),
        ActionApprovalStore(), state_directory=tmp_path / "memory")
    with pytest.raises(ValueError, match="schema"):
        owner.prepare("store", {"topic": "x", "content": "y", "extra": "z"})
    with pytest.raises(ValueError, match="searchable terms"):
        owner.prepare("recall", {"query": "--- !!!"})
    with pytest.raises(ValueError, match="id"):
        owner.prepare("forget", {"id": "../../other"})


def test_memory_confirmation_is_cancel_by_default():
    from textual.app import App
    from isycode.tui_screens_approval import MemoryConfirmScreen

    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(MemoryConfirmScreen("recall", "private query", sends_to_model=True),
                             results.append)

    async def run(action):
        async with Host().run_test() as pilot:
            await pilot.pause()
            await action(pilot)
            await pilot.pause()

    asyncio.run(run(lambda pilot: pilot.press("escape")))
    asyncio.run(run(lambda pilot: pilot.click("#memory-confirm-approve")))
    assert results == [False, True]


def test_tui_memory_tools_require_confirmation_and_mark_recall_untrusted(tmp_path):
    import json

    from isycode.tui_app_tools import ToolMixin

    class Host(ToolMixin):
        def __init__(self, allowed):
            self._workspace_root = tmp_path / "workspace"
            self._workspace_root.mkdir(exist_ok=True)
            self._action_approvals = ActionApprovalStore()
            self.allowed = allowed
            self.screens = []

        async def _await_screen(self, screen):
            self.screens.append(screen)
            return self.allowed

        def _append(self, message, color=None):
            pass

    async def run():
        denied = Host(False)
        response = json.loads(await denied._call_workspace_memory(
            "memory_store", {"topic": "test", "content": "not stored"}))
        assert response["status"] == "rejected_by_user"
        assert denied.screens[0].sends_to_model is False

        allowed = Host(True)
        response = json.loads(await allowed._call_workspace_memory(
            "memory_store", {"topic": "test", "content": "stored"}))
        assert response["stored"] is True
        assert allowed.screens[0].operation == "store"
        assert allowed.screens[0].sends_to_model is False

        reader = Host(True)
        response = json.loads(await reader._call_workspace_memory(
            "memory_recall", {"query": "stored"}))
        assert response["data"]["count"] == 1
        assert response["trust_notice"]
        assert reader.screens[0].sends_to_model is True

    asyncio.run(run())
