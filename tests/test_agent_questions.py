"""The agent can ask one bounded question. The answer grants nothing."""
import asyncio
import json

from isycode.actions import ACTION_BY_ID
from isycode.tui import TUIApp
from test_daily_tui import configure


def test_asking_the_user_is_not_an_authority_action():
    assert not any("ask" in action_id or "question" in action_id for action_id in ACTION_BY_ID)


def test_question_screen_returns_a_choice_text_or_cancellation(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            choice = asyncio.create_task(app._dispatch_chat_tool({
                "id": "q1",
                "function": {"name": "ask_user", "arguments": json.dumps({
                    "question": "Which fix?",
                    "choices": ["Keep the sibling", "Stage only the probe"],
                })},
            }))
            await pilot.pause()
            assert app.screen.id == "agent-question"
            await pilot.click("#ask-choice-1")
            call_id, payload = await choice
            assert call_id == "q1"
            assert json.loads(payload) == {
                "status": "answered", "choice": "Stage only the probe",
            }

            typed = asyncio.create_task(app._dispatch_chat_tool({
                "id": "q2",
                "function": {"name": "ask_user", "arguments": json.dumps({
                    "question": "Anything else?",
                })},
            }))
            await pilot.pause()
            app.screen.query_one("#ask-text").value = "ship it"
            await pilot.click("#ask-submit")
            assert json.loads((await typed)[1]) == {"status": "answered", "text": "ship it"}

            cancelled = asyncio.create_task(app._dispatch_chat_tool({
                "id": "q3",
                "function": {"name": "ask_user", "arguments": json.dumps({
                    "question": "Continue?",
                    "choices": ["Yes"],
                })},
            }))
            await pilot.pause()
            await pilot.press("escape")
            body = json.loads((await cancelled)[1])
            assert body == {"status": "cancelled"}
            assert "choice" not in body and "text" not in body

    with capsys.disabled():
        asyncio.run(scenario())
