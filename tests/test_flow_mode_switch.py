"""GF-05: switching mode in place invalidates old authorizations and keeps the chat."""
import asyncio

import pytest

from isycode.security import ActionRequest
from isycode.tui import TUIApp
from isycode.turn_journal import TurnJournal
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure


def _request(root):
    return ActionRequest("workspace.files.write", root, str(root / "app.py"),
                         {"path": "app.py"}, execution_owner="workspace_write")


def test_switch_clears_approvals_opens_and_closes_the_flow_turn_and_keeps_the_chat(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    root = (tmp_path / "project").resolve()

    async def scenario():
        app = TUIApp()

        async def no_startup():
            return None

        app._startup_workspace = no_startup
        async with app.run_test() as pilot:
            await pilot.pause()
            app._append("a human line in the conversation")
            lines_before = list(app._active_lane().lines)

            # An approval issued under the current mode must not survive a switch.
            token = app._action_approvals.issue(_request(root), ttl_seconds=60)

            await app._switch_engine_mode("flow")
            await pilot.pause()
            assert WorkspaceAuthority(root).mode() == "flow"
            assert not app._action_approvals.consume(_request(root), token)
            assert TurnJournal.active(root) is not None       # Flow opens a turn
            assert any("a human line" in str(line) for line in app._active_lane().lines)
            assert len(app._active_lane().lines) >= len(lines_before)

            await app._switch_engine_mode("security")
            await pilot.pause()
            assert WorkspaceAuthority(root).mode() == "security"
            assert TurnJournal.active(root) is None           # leaving Flow closes the turn

            await app._switch_engine_mode("classic")
            await pilot.pause()
            assert WorkspaceAuthority(root).mode() == "classic"
            assert any("a human line" in str(line) for line in app._active_lane().lines)

    with capsys.disabled():
        asyncio.run(scenario())


def test_switch_cancels_a_running_turn_then_restarts(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    root = (tmp_path / "project").resolve()

    async def scenario():
        app = TUIApp()

        async def no_startup():
            return None

        app._startup_workspace = no_startup
        async with app.run_test() as pilot:
            await pilot.pause()

            started = asyncio.Event()

            async def busy_turn():
                started.set()
                await asyncio.sleep(3600)

            app._chat_turn_task = asyncio.create_task(busy_turn())
            await started.wait()

            # Confirm the "a turn is running" screen and the cancel.
            async def confirm(screen):
                return True

            monkeypatch.setattr(app, "_await_screen", confirm)
            await app._switch_engine_mode("flow")
            await pilot.pause()

            assert app._chat_turn_task.cancelled() or app._chat_turn_task.done()
            assert WorkspaceAuthority(root).mode() == "flow"

    with capsys.disabled():
        asyncio.run(scenario())


def test_declining_the_running_turn_screen_keeps_the_mode(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    root = (tmp_path / "project").resolve()

    async def scenario():
        app = TUIApp()

        async def no_startup():
            return None

        app._startup_workspace = no_startup
        async with app.run_test() as pilot:
            await pilot.pause()
            assert WorkspaceAuthority(root).mode() == "classic"

            started = asyncio.Event()

            async def busy_turn():
                started.set()
                await asyncio.sleep(3600)

            app._chat_turn_task = asyncio.create_task(busy_turn())
            await started.wait()

            async def decline(screen):
                return False

            monkeypatch.setattr(app, "_await_screen", decline)
            await app._switch_engine_mode("flow")
            await pilot.pause()

            assert WorkspaceAuthority(root).mode() == "classic"   # unchanged
            assert not app._chat_turn_task.done()                 # turn untouched
            app._chat_turn_task.cancel()

    with capsys.disabled():
        asyncio.run(scenario())
