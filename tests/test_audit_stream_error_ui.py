"""Transport failures must not echo provider bodies into the chat UI."""
import asyncio

import pytest

from isycode.streaming import StreamError
from isycode.tui import ChatArea, PromptArea, TUIApp, plain_text
from test_daily_tui import configure


@pytest.mark.parametrize("partial", [False, True])
def test_stream_error_details_are_not_rendered(tmp_path, monkeypatch, partial):
    configure(tmp_path, monkeypatch)

    async def fail(provider, messages, **kwargs):
        if partial:
            kwargs["on_chunk"]("content", "Partial safe answer")
        raise StreamError("request failed: Bearer fictional-private-token; private-provider-body")

    monkeypatch.setattr("isycode.tui.provider_complete", fail)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._run_chat("Explain the parser")
            rendered = "\n".join(plain_text(widget) for widget in app.query_one(ChatArea).query("Static"))
            assert "fictional-private-token" not in rendered
            assert "private-provider-body" not in rendered
            assert app.query_one(PromptArea).text == "Explain the parser"
            assert app._history == []
    asyncio.run(scenario())
