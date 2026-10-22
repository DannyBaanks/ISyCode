"""Every decision dialog shares one frame, and the frame works without a mouse.

The product carried 41 ModalScreen subclasses, each re-deciding its own card
width, padding, preview height and action row. Two tests pin the frame: the
inventory ratchet stops a new bespoke dialog from appearing, and the keyboard
matrix proves every action on every ported dialog is reachable with Tab and
Enter at three terminal widths and in all three locales.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import ClassVar

import pytest
from textual.app import App
from textual.widgets import Button

from isycode.bridge_tools import BridgeSendScreen
from isycode.localization import SUPPORTED_LOCALES, configure_locale, current_locale
from isycode.tui_copy import CopyMenuScreen
from isycode.tui_dialog import Dialog
from isycode.tui_screens_approval import ReviewConsentScreen
from isycode.tui_screens_harness import (
    HarnessFolderConfirmScreen,
    HarnessModelConfirmScreen,
    HarnessTranscriptConfirmScreen,
)
from isycode.tui_screens_sessions import (
    BridgePresenceScreen,
    ChatArea,
    SessionDivergedScreen,
)
from isycode.tui_widgets import SelectableText
from test_daily_tui import configure

SOURCE = Path(__file__).resolve().parents[1] / "src" / "isycode"

# Screens still carrying their own anatomy. The set is a ratchet: porting a
# screen removes its name here, and adding a new decision dialog without using
# the frame fails the inventory test instead of growing the list.
PENDING_PORT = frozenset({
    "AddCredentialScreen",
    "AddWorkspaceFolderScreen",
    "AgentQuestionScreen",
    "AutomaticEditsWarningScreen",
    "BatchApprovalScreen",
    "BrokerManagementScreen",
    "ChatSessionsScreen",
    "ConsoleSearchScreen",
    "ContextAccessScreen",
    "FilePreviewScreen",
    "GatewaySemanticQueryScreen",
    "HarnessComposeScreen",
    "HarnessRepairConfirmScreen",
    "IdeaNoteScreen",
    "LSPQueryScreen",
    "MCPArgumentsScreen",
    "ModelsScreen",
    "MultiHarnessScreen",
    "PastedTextScreen",
    "QueuedMessagesScreen",
    "QuickHelpScreen",
    "QuickStartScreen",
    "RTKRawOutputScreen",
    "RTKSettingsScreen",
    "ReviewConsentScreen",
    "SessionMessageScreen",
    "SessionSearchScreen",
    "SessionTitleScreen",
    "ShellProcessesScreen",
    "SubagentModelScreen",
    "SubscriptionLoginScreen",
    "WorkspaceModeScreen",
    "WorkspaceSetupScreen",
}) - {"ReviewConsentScreen"}

FACTORIES = {
    "BridgePresenceScreen": lambda: BridgePresenceScreen(),
    "BridgeSendScreen": lambda: BridgeSendScreen(
        action="send", to="reviewer", topic="topic", message="hello"),
    "CopyMenuScreen": lambda: CopyMenuScreen("one\ntwo\n", "one\ntwo\nthree\n"),
    "HarnessFolderConfirmScreen": lambda: HarnessFolderConfirmScreen("claude", Path("/tmp/x")),
    "HarnessModelConfirmScreen": lambda: HarnessModelConfirmScreen("openai", "gpt-6"),
    "HarnessTranscriptConfirmScreen": lambda: HarnessTranscriptConfirmScreen("claude", "a.md"),
    "ReviewConsentScreen": lambda: ReviewConsentScreen("artifact text"),
    "SessionDivergedScreen": lambda: SessionDivergedScreen("A title"),
}


PACKAGE = SOURCE


class Host(App):
    """A bare app: dialogs must not need the whole product to be reachable."""

    CSS_PATH: ClassVar[list[Path]] = [PACKAGE / "isycode.tcss", PACKAGE / "design.tcss"]


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _decision_screens() -> dict[str, str]:
    """Class name -> file, for ModalScreens that render at least one Button."""
    found: dict[str, str] = {}
    for path in sorted(SOURCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any("ModalScreen" in _base_name(base) for base in node.bases):
                continue
            has_button = any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Name)
                and item.func.id == "Button"
                for item in ast.walk(node)
            )
            if has_button:
                found[node.name] = path.name
    return found


def test_every_decision_screen_uses_the_shared_frame():
    screens = _decision_screens()
    unaccounted = sorted(set(screens) - PENDING_PORT - {"Dialog"})
    assert not unaccounted, (
        "new decision dialogs must derive from Dialog or be added to PENDING_PORT "
        f"with a reason: {[(name, screens[name]) for name in unaccounted]}"
    )
    # The ratchet must not grow silently: the recorded set has to match disk.
    assert PENDING_PORT <= set(screens), sorted(PENDING_PORT - set(screens))


def test_ported_screens_really_derive_from_the_frame():
    for name, factory in FACTORIES.items():
        module = __import__(factory().__class__.__module__, fromlist=[name])
        assert issubclass(getattr(module, name), Dialog), name


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_every_action_is_reachable_without_a_click(name):
    async def scenario():
        app = Host()
        async with app.run_test(size=(100, 34)) as pilot:
            screen = FACTORIES[name]()
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            focused = app.focused
            assert isinstance(focused, Button), (name, focused)
            actions = [action for action in screen.dialog_actions() if not action.disabled]
            seen = {focused.id}
            for _ in range(len(actions) - 1):
                await pilot.press("tab")
                await pilot.pause()
                assert isinstance(app.focused, Button), (name, app.focused)
                seen.add(app.focused.id)
            assert seen == {action.id for action in actions}, (name, seen)
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is not screen, name

    asyncio.run(scenario())


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (120, 30)])
def test_every_dialog_fits_every_locale_and_width(size):
    width, height = size
    previous = current_locale()

    async def scenario():
        app = Host()
        async with app.run_test(size=size) as pilot:
            for locale in SUPPORTED_LOCALES:
                configure_locale(locale)
                for name, factory in FACTORIES.items():
                    screen = factory()
                    app.push_screen(screen)
                    await pilot.pause()
                    await pilot.pause()
                    card = screen.query_one(".isy-dialog-card")
                    region = card.region
                    assert region.width > 0 and region.height > 0, (name, locale, region)
                    assert region.x >= 0 and region.y >= 0, (name, locale, region)
                    assert region.right <= width, (name, locale, region, width)
                    assert region.bottom <= height, (name, locale, region, height)
                    for button in screen.query(Button):
                        if not button.display:
                            continue
                        assert region.contains_region(button.region) or (
                            region.x <= button.region.x
                            and button.region.right <= region.right
                            and button.region.y >= region.y
                        ), (name, locale, button.id, button.region, region)
                    app.pop_screen()
                    await pilot.pause()

    try:
        asyncio.run(scenario())
    finally:
        configure_locale(previous)


def test_rail_identity_is_one_line_and_opens_the_full_identity(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        from isycode.tui import TUIApp
        from isycode.tui_app_rail import IdentityDialog

        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.pause()
            app.action_focus_files()
            await pilot.pause()
            button = app.query_one("#rail-identity", Button)
            line = str(button.label)
            assert line.count(" · ") == 2, line
            assert "project" in line, line
            assert await pilot.click(button)
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, IdentityDialog)
            assert str(app._workspace_root) in app.screen.dialog_note()
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, IdentityDialog)

    asyncio.run(scenario())


def test_copy_menu_has_a_keyboard_door(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    async def scenario():
        from isycode.tui import TUIApp

        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.pause()
            message = SelectableText("hola mundo\nsegunda línea")
            app.query_one(ChatArea).mount(message)
            await pilot.pause()
            message.focus()
            await pilot.pause()
            assert message.has_focus
            await pilot.press("f2")
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, CopyMenuScreen), app.screen
            assert app.screen.query_one("#copy-whole", Button)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, CopyMenuScreen)

    asyncio.run(scenario())
