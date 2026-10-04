from isycode.pasted_text import PastedText


def test_readable_preview_retains_exact_payload():
    store = PastedText()
    payload = "Primeras palabras para reconocerlo\n" + "text " * 200
    label = store.capture(payload)
    assert label == '["Primeras palabras pa…"]'
    assert store.expand("Review " + label) == "Review " + payload
    assert store.capture("short") == "short"


def test_same_preview_different_payload_does_not_alias():
    store = PastedText()
    first = store.capture("same start " * 100 + "first")
    second = store.capture("same start " * 100 + "second")
    assert first != second
    assert store.expand(first + "\n" + second).endswith("second")
    assert store.expand(first).endswith("first")


def test_payload_is_not_recursively_expanded():
    store = PastedText()
    first = store.capture("first " * 200)
    second_payload = "second " * 200 + first
    second = store.capture(second_payload)
    assert store.expand(second) == second_payload


def test_terminal_paste_review_remove_and_lossless_send(tmp_path, monkeypatch):
    import asyncio
    from textual.events import Paste
    from isycode.tui import TUIApp, PastedTextScreen
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    received = []
    async def chat(self, text):
        received.append(text)
    monkeypatch.setattr(TUIApp, "_run_chat", chat)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            payload = "Recognizable content " * 100
            await prompt._on_paste(Paste(payload))
            await pilot.pause()
            assert len(prompt.text) < 40
            assert app._draft_text == payload
            await pilot.press("ctrl+p")
            await pilot.pause()
            assert isinstance(app.screen, PastedTextScreen)
            assert app.screen.items[0][1] == payload
            app.screen.query_one("#paste-remove-0").focus()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("escape")
            assert prompt.text == ""
            await prompt._on_paste(Paste(payload))
            app._accept_prompt(prompt, prompt.text)
            await pilot.pause()
            assert received == [payload.strip()]
    asyncio.run(scenario())
