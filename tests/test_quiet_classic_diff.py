"""Quiet Classic applies changes without a review screen, but never without showing the diff."""
import asyncio
import json

from textual.widgets import Collapsible

from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_trust import ACCEPT_PHRASE, WorkspaceTrust


async def _wait_for(pilot, predicate, description, timeout=10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if predicate():
            return
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError(f"Timed out waiting for {description}")
        await pilot.pause(min(0.05, remaining))


def test_quiet_classic_edit_and_delete_show_their_diff_in_the_chat(tmp_path, monkeypatch, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "notes.txt").write_text("hola\n")
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    from isycode.tui import TUIApp, ConfirmScreen
    from isycode.user_defaults import UserDefaultsStore

    UserDefaultsStore().update(new_workspace="recurring", new_workspace_mode="classic")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 45)) as pilot:
            authority = WorkspaceAuthority(project_dir.resolve())
            await _wait_for(
                pilot,
                lambda: isinstance(app.screen, ConfirmScreen)
                or WorkspaceTrust().trusted(authority),
                "quiet Classic trust prompt",
            )
            if isinstance(app.screen, ConfirmScreen):
                await pilot.press("y")  # trust this workspace (quiet Classic)
            await _wait_for(
                pilot, lambda: WorkspaceTrust().trusted(authority),
                "saved quiet Classic trust decision",
            )
            edited = json.loads(await app._dispatch_write_tool(
                {"path": "notes.txt", "old_text": "hola", "new_text": "hola mundo"}, edit=True))
            assert edited["status"] == "written" and edited["approval_mode"] == "quiet-profile"
            deleted = json.loads(await app._dispatch_file_change(
                "workspace_delete", {"path": "notes.txt"}))
            assert deleted["status"] == "done"
            await pilot.pause()
            assert app.screen is app.screen_stack[0]  # no review screen was opened
            cards = [card for card in app.query(Collapsible) if card.has_class("applied-diff")]
            titles = [str(card.title) for card in cards]
            assert len(cards) == 2, titles
            assert all("notes.txt" in title for title in titles)
            assert "+1 −1" in titles[0] and "−1" in titles[1]

    with capsys.disabled():
        asyncio.run(scenario())
