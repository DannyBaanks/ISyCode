"""Every approval opens on its refusing action, even with a long scrolling body (freeze fix)."""
import asyncio
import inspect

from textual.app import App
from textual.widgets import Button

from isycode import tui_screens_approval
from isycode.tui_screens_approval import ApprovalScreen, TailscaleConfirmScreen


def test_the_whole_approval_family_auto_focuses_its_first_button():
    assert ApprovalScreen.AUTO_FOCUS == "Button"
    family = [cls for _, cls in inspect.getmembers(tui_screens_approval, inspect.isclass)
              if issubclass(cls, ApprovalScreen) and cls is not ApprovalScreen]
    assert len(family) >= 9
    for cls in family:
        # A subclass may name its refusing button, never fall back to the app default.
        assert cls.AUTO_FOCUS not in (None, "*"), cls.__name__


def test_a_long_approval_opens_on_reject_and_enter_refuses():
    results = []

    class Host(App):
        def on_mount(self):
            body = "\n".join(f"line {index} of a long review" for index in range(200))
            self.push_screen(TailscaleConfirmScreen("Allow this?", body, "Allow"), results.append)

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(pilot.app.screen.focused, Button):
                    break
            screen = pilot.app.screen
            assert screen.focused is screen.query(Button).first()
            await pilot.press("enter")
            for _ in range(40):
                if results:
                    break
                await pilot.pause(0.05)
            assert results == [False]

    asyncio.run(scenario())
