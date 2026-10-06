"""M8: polished, accessible UX gates.

G8-01 keyboard-only with safe defaults, G8-02 real resize with the
draft intact, G8-03 objective contrast (evidence: test_side_panel WCAG
test), G8-04 1000 tool events keep order and never show a failure as
completed, G8-05 compact receipts with decision/scope/budget/recovery
and no secret canary.
"""
import asyncio

import pytest

from isycode.tui import TUIApp, WriteApprovalScreen
from isycode.tui_widgets import ChatArea, ExpandableBox, ToolActivityGroup
from test_daily_tui import configure

CANARY = "sk-m8receiptcanary0123456789"


@pytest.mark.asyncio
async def test_reject_button_is_the_default_focus(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        from isycode.workspace_write import WorkspaceWriteOwner
        from isycode.approvals import ActionApprovalStore
        from isycode.workspace_authority import WorkspaceAuthority
        root = app._workspace_root
        owner = WorkspaceWriteOwner(root, WorkspaceAuthority(root), ActionApprovalStore())
        await app.push_screen(WriteApprovalScreen(owner.preview("a.txt", "x\n")))
        await pilot.pause()
        assert app.screen.query_one("#write-approval-reject").has_focus
        await pilot.press("enter")
        await pilot.pause()


@pytest.mark.asyncio
async def test_resize_200x60_and_back_keeps_composer_and_draft(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(200, 60)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input")
        prompt.load_text("draft at 200x60 must survive resizes")
        await pilot.pause()
        composer = app.query_one("#composer")
        rail = app.query_one("#side-panel")
        assert composer.region.width > 0 and not composer.region.overlaps(rail.region)
        assert app.query_one("#settings-button").display
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert prompt.text == "draft at 200x60 must survive resizes"
        await pilot.resize_terminal(200, 60)
        await pilot.pause()
        assert prompt.text == "draft at 200x60 must survive resizes"
        assert not composer.region.overlaps(app.query_one("#side-panel").region)


@pytest.mark.asyncio
async def test_thousand_tool_events_keep_order_and_failed_stays_failed(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        chat = app.query_one(ChatArea)
        first = ExpandableBox(title="leaf 1")
        group = ToolActivityGroup("workspace_read", first, "read 1")
        await chat.mount(group)
        for index in range(2, 11):
            await group.add_leaf(ExpandableBox(title=f"leaf {index}"), f"read {index}")
        mounted = group.query_one(group.Contents).mount
        async def fast_mount(widget):
            return None
        group.query_one(group.Contents).mount = fast_mount
        try:
            for index in range(11, 1001):
                await group.add_leaf(ExpandableBox(title=f"leaf {index}"), f"read {index}")
        finally:
            group.query_one(group.Contents).mount = mounted
        assert len(group.leaves) == 1000
        assert [label for _, label in group.leaves][:3] == ["read 1", "read 2", "read 3"]
        assert [label for _, label in group.leaves][-1] == "read 1000"
        failed_leaf = group.leaves[500][0]
        group.finish_leaf(failed_leaf, "read 501 · Failed · 1s")
        labels = [label for _, label in group.leaves]
        assert labels[500] == "read 501 · Failed · 1s"
        assert "Completed" not in labels[500]
        assert group.title == "workspace_read · 1000 calls"


@pytest.mark.asyncio
async def test_receipt_expands_decision_scope_budget_recovery_without_canary(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        root = app._workspace_root
        (root / "notes.txt").write_text(f"token is {CANARY}\n", encoding="utf-8")
        from isycode.action_runtime import LocalWorkspaceReadOwner
        from isycode.workspace_authority import WorkspaceAuthority
        owner = LocalWorkspaceReadOwner(root, WorkspaceAuthority(root))
        result = owner.execute("workspace.files.read", {"path": "notes.txt"})
        assert result.decision == "ALLOW"
        text = app._receipt_text(result, f"read notes.txt · {CANARY}")
        assert "Decision · ALLOW" in text
        assert result.receipt.receipt_id in text
        assert "Scope ·" in text
        assert "Budget ·" in text and "remaining" in text
        assert "Recovery · /undo" in text
        assert CANARY not in text
