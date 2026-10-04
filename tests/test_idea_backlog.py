import asyncio
from isycode.tui import TUIApp, PromptArea, IdeaBacklogScreen
from test_daily_tui import configure


def test_ideas_are_not_sent_until_explicit_promotion(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            prompt = app.query_one(PromptArea)
            prompt.load_text("A new feature idea")
            prompt.action_capture_idea()
            assert app._idea_backlog == ["A new feature idea"]
            assert not app._queued_messages and not app._history
            app.push_screen(IdeaBacklogScreen(app))
            await pilot.pause()
            fold = app.screen.query_one("Collapsible")
            fold.collapsed = False
            await pilot.pause()
            await pilot.click("#idea-promote-0")
            await pilot.pause()
            assert app._queued_messages == ["A new feature idea"]
            assert not app._idea_backlog and not app._history
    asyncio.run(scenario())
