"""M-UX2: batch approvals and session trust, inside the M15 model.

Batch = one human gesture that lets the app issue N single-use,
digest-bound approvals (one per file). It never creates a persistent
grant. Session trust = in-memory, Classic-only, dies with the process,
suspended by a mode change, and every write still gets its own fresh
token and receipt.
"""
import asyncio
import json

import pytest

from isycode.tui import TUIApp, WriteApprovalScreen
from isycode.tui_screens_approval import BatchApprovalScreen
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure


def _write_call(call_id, path, content):
    return {"id": call_id, "type": "function",
            "function": {"name": "workspace_write",
                         "arguments": json.dumps({"path": path, "content": content})}}


def _edit_call(call_id, path, old, new):
    return {"id": call_id, "type": "function",
            "function": {"name": "workspace_edit",
                         "arguments": json.dumps({"path": path, "old_text": old, "new_text": new})}}


@pytest.mark.asyncio
async def test_batch_screen_lists_every_diff_and_defaults_to_reject(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        from isycode.workspace_write import WorkspaceWriteOwner
        from isycode.approvals import ActionApprovalStore
        root = app._workspace_root
        (root / "a.txt").write_text("a\n")
        owner = WorkspaceWriteOwner(root, WorkspaceAuthority(root), ActionApprovalStore())
        previews = [owner.preview("a.txt", "b\n"), owner.preview("b.txt", "new\n")]
        screen = BatchApprovalScreen(previews)
        await app.push_screen(screen)
        await pilot.pause()
        text = str(app.screen.query_one("#batch-approval-summary").content)
        assert "single-use" in text and "no lasting permission" in text
        assert app.screen.query_one("#batch-approval-reject").has_focus
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_batch_approve_all_applies_each_with_its_own_receipt(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    root_holder = {}
    app = TUIApp()

    async def fake_screen(screen):
        root_holder["screen"] = screen
        return "all"

    async def scenario(pilot):
        app._await_screen = fake_screen
        root = app._workspace_root
        (root / "a.txt").write_text("a\n")
        calls = [_edit_call("c1", "a.txt", "a", "b"), _write_call("c2", "b.txt", "new\n")]
        app._batch_decisions = decisions = await app._review_write_batch(calls)
        assert set(decisions) == {"c1", "c2"}
        assert all(len(value) == 64 for value in decisions.values())
        for call in calls:
            call_id, result = await app._dispatch_chat_tool(call)
            payload = json.loads(result)
            assert payload["status"] == "written", payload
            assert payload["approval_mode"] == "batch"
        assert (root / "a.txt").read_text() == "b\n"
        assert (root / "b.txt").read_text() == "new\n"

    async with app.run_test(size=(120, 40)) as pilot:
        await scenario(pilot)


@pytest.mark.asyncio
async def test_batch_reject_all_writes_nothing(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()

    async def fake_screen(screen):
        return "reject"

    async with app.run_test(size=(120, 40)) as pilot:
        app._await_screen = fake_screen
        root = app._workspace_root
        calls = [_write_call("c1", "a.txt", "x\n"), _write_call("c2", "b.txt", "y\n")]
        app._batch_decisions = decisions = await app._review_write_batch(calls)
        assert decisions == {"c1": "reject", "c2": "reject"}
        for call in calls:
            _, result = await app._dispatch_chat_tool(call)
            assert json.loads(result)["status"] == "rejected_by_user"
        assert not (root / "a.txt").exists() and not (root / "b.txt").exists()


@pytest.mark.asyncio
async def test_batch_skips_same_path_and_single_candidate(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()

    async def fake_screen(screen):
        raise AssertionError("no batch screen expected")

    async with app.run_test(size=(120, 40)) as pilot:
        app._await_screen = fake_screen
        calls = [_write_call("c1", "a.txt", "x\n"), _write_call("c2", "a.txt", "y\n")]
        assert await app._review_write_batch(calls) == {}
        assert await app._review_write_batch([_write_call("c1", "b.txt", "y\n")]) == {}


@pytest.mark.asyncio
async def test_batch_digest_drift_reopens_individual_review(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    seen = []

    async def fake_screen(screen):
        seen.append(type(screen).__name__)
        if isinstance(screen, WriteApprovalScreen):
            return True
        return "all"

    async with app.run_test(size=(120, 40)) as pilot:
        app._await_screen = fake_screen
        root = app._workspace_root
        calls = [_write_call("c1", "a.txt", "x\n"), _write_call("c2", "b.txt", "y\n")]
        app._batch_decisions = decisions = await app._review_write_batch(calls)
        assert set(decisions) == {"c1", "c2"}
        (root / "a.txt").write_text("surprise\n")
        _, result = await app._dispatch_chat_tool(calls[0])
        assert "WriteApprovalScreen" in seen


@pytest.mark.asyncio
async def test_session_trust_button_only_in_classic_and_applies(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    choices = iter(["session"])

    async def fake_screen(screen):
        assert isinstance(screen, WriteApprovalScreen)
        assert screen.allow_session_trust is True
        return next(choices)

    async with app.run_test(size=(120, 40)) as pilot:
        app._await_screen = fake_screen
        root = app._workspace_root
        _, result = await app._dispatch_chat_tool(_write_call("c1", "a.txt", "one\n"))
        assert json.loads(result)["status"] == "written"
        assert "main" in app._session_auto_edits
        app._await_screen = lambda screen: (_ for _ in ()).throw(
            AssertionError("second write must not open a modal"))
        _, result = await app._dispatch_chat_tool(_write_call("c2", "b.txt", "two\n"))
        payload = json.loads(result)
        assert payload["status"] == "written"
        assert payload["approval_mode"] == "session-trust"
        assert payload["receipt"]


@pytest.mark.asyncio
async def test_session_trust_persists_nothing_and_dies_with_the_app(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        root = app._workspace_root
        app._session_auto_edits.add("main")
        store_path = app._folder_store().path
        before = store_path.read_bytes() if store_path.exists() else b""
        policy = WorkspaceAuthority(root).policy()
        assert "auto_edit" not in str(policy.get("grants", {}))
        app2 = TUIApp()
        assert app2._session_auto_edits == set()
        after = store_path.read_bytes() if store_path.exists() else b""
        assert before == after


@pytest.mark.asyncio
async def test_session_trust_never_shows_in_security_mode(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        root = app._workspace_root
        WorkspaceAuthority(root).set_mode("security")
        from isycode.workspace_write import WorkspaceWriteOwner
        from isycode.approvals import ActionApprovalStore
        owner = WorkspaceWriteOwner(root, WorkspaceAuthority(root), ActionApprovalStore())
        preview = owner.preview("a.txt", "x\n")
        screen = WriteApprovalScreen(
            preview, allow_session_trust=app._folder_store().auto_edit_available("main"))
        assert screen.allow_session_trust is False
        assert app._session_trust_active("main") is False


@pytest.mark.asyncio
async def test_session_trust_suspended_by_mode_change(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        root = app._workspace_root
        app._session_auto_edits.add("main")
        assert app._session_trust_active("main") is True
        WorkspaceAuthority(root).set_mode("security")
        assert app._session_trust_active("main") is False
        WorkspaceAuthority(root).set_mode("classic")
        assert app._session_trust_active("main") is True


def test_single_use_tokens_still_replay_fail():
    from isycode.approvals import ActionApprovalStore
    from isycode.security import ActionRequest
    from pathlib import Path
    store = ActionApprovalStore()
    root = Path(__file__).resolve().parents[1]
    request = ActionRequest("workspace.files.write", root, "a.txt", {},
                            execution_owner="workspace_write")
    approval = store.issue(request)
    assert store.consume(request, approval) is True
    assert store.consume(request, approval) is False
