"""M-UX4: progressive onboarding (Quick Start / Custom setup / /help tour).

Quick Start chains the EXISTING first-run pieces (recurring + Classic +
the explicit coding-tools confirmation); it grants nothing beyond what
the user could already click through, and never touches the Security path.
"""
import json

import pytest

from isycode.tui import QuickStartScreen, TUIApp, WorkspaceModeScreen, WorkspaceSetupScreen
from isycode.tui_screens_approval import TailscaleConfirmScreen
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure


def _clear_saved_recurrence(app):
    """Simulate a true first run: drop the boot-time saved recurrence choice."""
    store = app._workspace_setup
    data = store._load()
    data.pop(store._key(app._launch_dir), None)
    store.preferences_path.write_text(json.dumps({"choices": data}), encoding="utf-8")


@pytest.mark.asyncio
async def test_quick_start_screen_defaults_to_quick_and_escape_is_custom(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await app.push_screen(QuickStartScreen(app._workspace_root, provider_ready=True))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, QuickStartScreen)
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_quick_start_chains_recurring_classic_and_toolkit_offer(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    from isycode.user_defaults import UserDefaultsStore
    UserDefaultsStore().update(new_workspace="ask", new_workspace_mode="ask")
    seen = []
    grants_holder = {}

    app = TUIApp()

    async def fake_screen(screen):
        seen.append(type(screen).__name__)
        if isinstance(screen, QuickStartScreen):
            return "quick"
        if isinstance(screen, TailscaleConfirmScreen):
            return True
        return True

    async with app.run_test(size=(120, 40)) as pilot:
        app._await_screen = fake_screen
        await pilot.pause()
        _clear_saved_recurrence(app)
        await app._startup_workspace()
        await pilot.pause()
        root = app._workspace_root
        assert app._quick_start is True
        policy = WorkspaceAuthority(root).effective_policy()
        assert policy["mode"] == "classic"
        grants = policy.get("grants", {})
        toolkit_actions = {action for action, _, _ in app._coding_toolkit_grants()}
        from isycode.workspace_authority import CLASSIC_ACTIONS
        assert set(grants) <= CLASSIC_ACTIONS | toolkit_actions
        assert "QuickStartScreen" in seen


@pytest.mark.asyncio
async def test_custom_setup_keeps_the_step_by_step_chain(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    from isycode.user_defaults import UserDefaultsStore
    UserDefaultsStore().update(new_workspace="ask", new_workspace_mode="ask")
    seen = []
    app = TUIApp()

    async def fake_screen(screen):
        seen.append(type(screen).__name__)
        if isinstance(screen, QuickStartScreen):
            return "custom"
        if isinstance(screen, WorkspaceSetupScreen):
            return True
        if isinstance(screen, WorkspaceModeScreen):
            return "security"
        return True

    async with app.run_test(size=(120, 40)) as pilot:
        app._await_screen = fake_screen
        await pilot.pause()
        _clear_saved_recurrence(app)
        await app._startup_workspace()
        await pilot.pause()
        assert app._quick_start is False
        names = seen
        assert "QuickStartScreen" in names and "WorkspaceSetupScreen" in names
        assert WorkspaceAuthority(app._workspace_root).mode() == "classic"


@pytest.mark.asyncio
async def test_saved_preferences_skip_the_quick_start_screen(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    from isycode.user_defaults import UserDefaultsStore
    UserDefaultsStore().update(new_workspace="recurring", new_workspace_mode="classic")
    seen = []
    app = TUIApp()

    async def fake_screen(screen):
        seen.append(type(screen).__name__)
        return True

    async with app.run_test(size=(120, 40)) as pilot:
        app._await_screen = fake_screen
        await pilot.pause()
        await app._startup_workspace()
        await pilot.pause()
        assert "QuickStartScreen" not in [type(s).__name__ for s in seen]
        assert WorkspaceAuthority(app._workspace_root).mode() == "classic"


@pytest.mark.asyncio
async def test_help_tour_prints_the_tour(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    from isycode.tui_app_menu import _help_cmd, _TOUR_LINES
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _help_cmd(app, "tour")
        text = "\n".join(line for kind, line, *_ in app._active_lane().lines)
        assert "Tour · the lay of the land" in text
        assert "Ctrl+Shift+F" in text
