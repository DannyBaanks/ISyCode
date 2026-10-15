"""Render isolated real Textual screens; no live provider/clipboard calls."""
import asyncio
import json
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from pytest import MonkeyPatch
from rich.text import Text
from test_daily_tui import configure
from textual.widgets import OptionList
from isycode.tui import TUIApp, ChatArea, TailscaleConfirmScreen, ModelsScreen, MultiHarnessScreen, WorkspaceSetupScreen
from isycode.tui_copy import CopyMenuScreen
from isycode.tui_widgets import ExpandableBox, SelectableText, CommandOutputCard
from isycode.localization import configure_locale

OUTPUT = Path(__file__).resolve().parent / ("snapshots-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
OUTPUT.mkdir()


async def main():
    with tempfile.TemporaryDirectory(prefix="isycode-design-") as temp, MonkeyPatch.context() as patch:
        root = configure(Path(temp), patch)
        (root / "example.py").write_text("def helper():\n    x = 1\n    y = 2\n    return x + y\n")
        patch.delenv("NO_COLOR", raising=False)
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._locale = "es"
            configure_locale("es")
            app._apply_locale_chrome()
            async def capture(name):
                await pilot.pause()
                app.save_screenshot(str(OUTPUT / f"{name}-color.svg"))
            app._set_rail_view("overview")
            await capture("inicio-sidebar")
            app._open_settings_menu()
            categories = app.query_one("#settings-categories", OptionList)
            categories.highlighted = 1
            await capture("settings")
            await pilot.resize_terminal(80, 24)
            await capture("settings-80x24")
            await pilot.resize_terminal(120, 40)
            app._close_menu()
            app._open_provider_menu()
            await capture("providers")
            app._close_menu()
            app.push_screen(ModelsScreen([
                {"kind": "model", "value": "openai|gpt-6-luna", "label": "GPT 6 Luna"},
                {"kind": "model", "value": "openai|gpt-6-sol", "label": "GPT 6 Sol"},
            ], provider_scope="openai"))
            await capture("models")
            await pilot.press("escape")
            app.push_screen(MultiHarnessScreen())
            await capture("harness")
            await pilot.press("escape")
            app._open_authority_menu()
            await capture("authority")
            app._close_menu()
            app._set_rail_view("files")
            await app._load_directory(str(root))
            await app._preview_file(str(root / "example.py"))
            await capture("files")
            app._set_rail_view("overview")
            chat = app.query_one(ChatArea)
            box = ExpandableBox(SelectableText(Text("def helper():\n    x = 1\n    y = 2\n    return x + y\n")), title="Texto", collapsed=False)
            await chat.mount(box)
            card = CommandOutputCard("python3 example.py")
            await chat.mount(card)
            card.finish("exit code 0", output="1\n2\n3\n", receipt="illustrative-receipt")
            box.scroll_visible(animate=False)
            app.push_screen(CopyMenuScreen("    x = 1\n    y = 2", box.copy_text()))
            await capture("copy-menu")
            await pilot.press("escape")
            app.push_screen(TailscaleConfirmScreen("Switch this workspace to Security?", "Everything starts off; you allow each capability in Settings → Authority. Permissions you granted explicitly stay as they are.", "Use Security"))
            await capture("confirmation")
            await pilot.press("escape")
            await pilot.resize_terminal(80, 24)
            app.push_screen(WorkspaceSetupScreen(root / ("project-" + "x" * 180)))
            await capture("onboarding-80x24")
    print("Native Textual SVG snapshots saved; isolated fixture data, no live services.")
    print(OUTPUT)


if __name__ == "__main__":
    asyncio.run(main())
