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

            async def wait_for_screen(screen_id):
                async def wait_until_visible():
                    while app.screen.id != screen_id:
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(wait_until_visible(), timeout=10)
                await pilot.pause()

            choice = asyncio.create_task(app._dispatch_chat_tool({
                "id": "q1",
                "function": {"name": "ask_user", "arguments": json.dumps({
                    "question": "Which fix?",
                    "choices": ["Keep the sibling", "Stage only the probe"],
                })},
            }))
            await wait_for_screen("agent-question")
            await asyncio.wait_for(pilot.click("#ask-choice-1"), timeout=10)
            call_id, payload = await asyncio.wait_for(choice, timeout=10)
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
            await wait_for_screen("agent-question")
            answer = app.screen.query_one("#ask-text")
            assert answer.has_focus
            answer.value = "ship it"
            await asyncio.wait_for(pilot.click("#ask-submit"), timeout=10)
            assert json.loads((await asyncio.wait_for(typed, timeout=10))[1]) == {
                "status": "answered", "text": "ship it",
            }

            cancelled = asyncio.create_task(app._dispatch_chat_tool({
                "id": "q3",
                "function": {"name": "ask_user", "arguments": json.dumps({
                    "question": "Continue?",
                    "choices": ["Yes"],
                })},
            }))
            await wait_for_screen("agent-question")
            await asyncio.wait_for(pilot.press("escape"), timeout=10)
            body = json.loads((await asyncio.wait_for(cancelled, timeout=10))[1])
            assert body == {"status": "cancelled"}
            assert "choice" not in body and "text" not in body

    with capsys.disabled():
        asyncio.run(scenario())
