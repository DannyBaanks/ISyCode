"""TUI integration of the reviewed, single-approval edit pack."""
import json

import pytest

from isycode.tui import TUIApp
from isycode.tui_screens_approval import BatchApprovalScreen
from test_daily_tui import configure


def _call(edits):
    return {"id": "pack-1", "type": "function", "function": {
        "name": "workspace_edit_pack", "arguments": json.dumps({"edits": edits})}}


@pytest.mark.asyncio
async def test_edit_pack_reviews_every_diff_and_applies_once(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    seen = []

    async def approve(screen):
        seen.append(screen)
        return "all"

    async with app.run_test(size=(120, 40)) as pilot:
        app._await_screen = approve
        root = app._workspace_root
        (root / "a.txt").write_text("a\n")
        (root / "b.txt").write_text("b\n")
        call_id, result = await app._dispatch_chat_tool(_call([
            {"path": "a.txt", "old_text": "a", "new_text": "A"},
            {"path": "b.txt", "content": "B\n"},
        ]))
        await pilot.pause()
        payload = json.loads(result)
        assert call_id == "pack-1"
        assert payload["status"] == "written", payload
        assert payload["approval_mode"] == "reviewed"
        assert payload["approved_by_user"] is True
        assert payload["paths"] == ["a.txt", "b.txt"]
        assert payload["receipt"].startswith("rcpt_txn_")
        assert (root / "a.txt").read_text() == "A\n"
        assert (root / "b.txt").read_text() == "B\n"
        assert len(seen) == 1 and isinstance(seen[0], BatchApprovalScreen)
        assert seen[0].transaction is True
        assert [preview.path for preview in seen[0].previews] == ["a.txt", "b.txt"]


@pytest.mark.asyncio
async def test_edit_pack_reject_writes_nothing(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()

    async def reject(screen):
        assert isinstance(screen, BatchApprovalScreen)
        return "reject"

    async with app.run_test(size=(120, 40)):
        app._await_screen = reject
        root = app._workspace_root
        (root / "a.txt").write_text("a\n")
        _, result = await app._dispatch_chat_tool(_call([
            {"path": "a.txt", "content": "A\n"},
            {"path": "new.txt", "content": "new\n"},
        ]))
        assert json.loads(result)["status"] == "rejected_by_user"
        assert (root / "a.txt").read_text() == "a\n"
        assert not (root / "new.txt").exists()


@pytest.mark.asyncio
async def test_session_trust_does_not_silence_edit_pack_review(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    seen = []

    async def reject(screen):
        seen.append(type(screen).__name__)
        return "reject"

    async with app.run_test(size=(120, 40)):
        app._await_screen = reject
        app._session_auto_edits.add("main")
        root = app._workspace_root
        (root / "a.txt").write_text("a\n")
        _, result = await app._dispatch_chat_tool(_call([
            {"path": "a.txt", "content": "A\n"}]))
        assert json.loads(result)["status"] == "rejected_by_user"
        assert seen == ["BatchApprovalScreen"]
        assert (root / "a.txt").read_text() == "a\n"
