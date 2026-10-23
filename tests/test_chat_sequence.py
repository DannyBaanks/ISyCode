from isycode.tui import plain_text
import asyncio
import json
import pytest

from textual.widgets import Static

from isycode.tui import ChatArea, TUIApp, ThoughtBlock
from isycode.conversation_lane import ConversationLane
from isycode.tui_widgets import SelectableText
from test_daily_tui import configure


def test_model_steps_and_owned_tools_stay_in_display_order(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    (root / 'first.py').write_text('first = 1\n')
    (root / 'second.py').write_text('second = 2\n')
    rounds = []
    async def complete(provider, messages, **kwargs):
        index = len(rounds)
        rounds.append(index)
        kwargs['on_chunk']('reasoning', f'Reasoning {index + 1}')
        kwargs['on_chunk']('content', f'Explanation {index + 1}.')
        if index < 2:
            path = ('first.py', 'second.py')[index]
            return {'text': f'Explanation {index + 1}.', 'tool_calls': [
                {'id': f'call-{index}', 'type': 'function', 'function': {
                    'name': 'workspace_read', 'arguments': json.dumps({'path': path})}}]}
        return {'text': 'Explanation 3.', 'tool_calls': []}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app._run_chat('Inspect both files.')
            await pilot.pause()
            rows = []
            for child in app.query_one(ChatArea).children:
                if isinstance(child, ThoughtBlock):
                    rows.append(plain_text(child._body))
                elif child.has_class('tool-activity'):
                    rows.append(str(child.title))
                elif isinstance(child, Static):
                    rows.append(app._render_searchable_text(child))
            positions = [next(i for i, row in enumerate(rows) if text in row) for text in (
                'Reasoning 1', 'Explanation 1.', 'workspace_read · first.py',
                'Reasoning 2', 'Explanation 2.', 'workspace_read · second.py',
                'Reasoning 3', 'Explanation 3.')]
            assert positions == sorted(set(positions))
            assert len(app.query(ThoughtBlock)) == 3
            assert app._history[-1]['content'] == 'Explanation 1.\n\nExplanation 2.\n\nExplanation 3.'
    with capsys.disabled():
        asyncio.run(scenario())


def test_stream_follows_bottom_but_respects_history_reading(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    ready, continue_stream = asyncio.Event(), asyncio.Event()
    text = 'Long streamed paragraph.\n\n' * 30
    async def complete(provider, messages, **kwargs):
        kwargs['on_chunk']('content', text)
        ready.set()
        await continue_stream.wait()
        kwargs['on_chunk']('content', text)
        return {'text': text * 2, 'tool_calls': []}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            chat = app.query_one(ChatArea)
            task = asyncio.create_task(app._run_chat('Explain.'))
            await ready.wait()
            await pilot.pause()
            assert chat.max_scroll_y > 0
            assert abs(chat.scroll_y - chat.max_scroll_y) <= 1
            chat.focus()
            await pilot.press('home')
            # Textual animates Home by default; wait for that animation before
            # comparing the scroll position after another streamed chunk.
            await pilot.pause(1.1)
            assert chat.scroll_y < chat.max_scroll_y
            before = chat.scroll_y
            continue_stream.set()
            await task
            await pilot.pause()
            assert chat.scroll_y == before
            await pilot.press('end')
            await pilot.pause()
            app._append('New output after returning to bottom.')
            await pilot.pause()
            assert abs(chat.scroll_y - chat.max_scroll_y) <= 1
    with capsys.disabled():
        asyncio.run(scenario())


def test_rendering_search_text_does_not_write_to_terminal(capsys):
    from rich.text import Text
    text = TUIApp._render_searchable_text(Static(Text('Search marker')))
    assert 'Search marker' in text
    assert capsys.readouterr().out == ''


def test_returned_text_without_stream_callbacks_precedes_its_tool(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    (root / 'first.py').write_text('value = 1\n')
    calls = []
    async def complete(provider, messages, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            return {'text': 'Checking first.py.', 'tool_calls': [{'id': 'read-one', 'type': 'function',
                    'function': {'name': 'workspace_read', 'arguments': '{"path":"first.py"}'}}]}
        return {'text': 'Finished.', 'tool_calls': []}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._run_chat('Read the file.')
            await pilot.pause()
            rows = [str(w.title) if w.has_class('tool-activity') else app._render_searchable_text(w)
                    for w in app.query_one(ChatArea).children
                    if isinstance(w, Static) or w.has_class('tool-activity')]
            positions = [next(i for i, row in enumerate(rows) if text in row)
                         for text in ('Checking first.py.', 'workspace_read · first.py', 'Finished.')]
            assert positions == sorted(set(positions))
            assert app._history[-1]['content'] == 'Checking first.py.\n\nFinished.'
            assert not app.query(ThoughtBlock)
    with capsys.disabled():
        asyncio.run(scenario())


def test_search_history_stays_visible_during_new_output(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._append('Old searchable marker.')
            for i in range(60):
                app._append(f'Later message {i}.')
            chat = app.query_one(ChatArea)
            # Following new output scrolls after layout; give a loaded runner time.
            for _ in range(100):
                await pilot.pause(0.05)
                if chat.max_scroll_y and abs(chat.scroll_y - chat.max_scroll_y) <= 1:
                    break
            assert abs(chat.scroll_y - chat.max_scroll_y) <= 1
            from unittest.mock import Mock
            app._search_console('Old searchable marker', Mock())
            # _show_console_search_match schedules the scroll after refresh;
            # one pause is not enough when the rest of the suite is under load.
            for _ in range(100):
                await pilot.pause(0.05)
                if chat.scroll_y < chat.max_scroll_y:
                    break
            before = chat.scroll_y
            assert before < chat.max_scroll_y
            app._append('Another new message.')
            for _ in range(20):
                await pilot.pause(0.05)
                if chat.max_scroll_y > before:
                    break
            assert chat.scroll_y == before
    with capsys.disabled():
        asyncio.run(scenario())


def test_reasoning_growth_and_collapse_keep_tail_visible(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    growing, continue_stream = asyncio.Event(), asyncio.Event()
    async def complete(provider, messages, **kwargs):
        kwargs['on_chunk']('reasoning', 'Reasoning line.\n' * 70)
        growing.set()
        await continue_stream.wait()
        kwargs['on_chunk']('content', 'Final answer paragraph.\n\n' * 30)
        return {'text': 'Final answer paragraph.\n\n' * 30, 'tool_calls': []}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._run_chat('Explain.'))
            await growing.wait()
            await pilot.pause()
            chat = app.query_one(ChatArea)

            async def tail_visible():
                # Slow runners (Windows CI) can sample mid-relayout, when the
                # scroll offset is briefly out of range; wait for it to settle.
                for _ in range(100):
                    if abs(chat.scroll_y - chat.max_scroll_y) <= 1:
                        return True
                    await pilot.pause(0.02)
                return False

            try:
                assert app.query_one(ThoughtBlock)._body.region.height == 2
                assert await tail_visible(), (chat.scroll_y, chat.max_scroll_y)
            finally:
                continue_stream.set()
                await task
            await pilot.pause()
            assert await tail_visible(), (chat.scroll_y, chat.max_scroll_y)
            assert app.query_one(ThoughtBlock).collapsed
    with capsys.disabled():
        asyncio.run(scenario())


def test_fast_reasoning_round_preserves_history_position(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    async def complete(provider, messages, **kwargs):
        kwargs['on_chunk']('reasoning', 'A quick thought.')
        kwargs['on_chunk']('content', 'A quick answer.')
        return {'text': 'A quick answer.', 'tool_calls': []}
    monkeypatch.setattr('isycode.tui.provider_complete', complete)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for i in range(60):
                app._append(f'History message {i}.')
            await pilot.pause()
            chat = app.query_one(ChatArea)
            chat.focus()
            await pilot.press('home')
            # Let Textual finish its default one-second Home animation before
            # asserting that a fast response leaves history at the same offset.
            await pilot.pause(1.1)
            before = chat.scroll_y
            await app._run_chat('Answer quickly.')
            await pilot.pause()
            assert chat.scroll_y == before
    with capsys.disabled():
        asyncio.run(scenario())


def test_fast_consecutive_reasoning_chunks_share_one_visible_block(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def complete(provider, messages, **kwargs):
        kwargs['on_chunk']('reasoning', 'First thought. ')
        kwargs['on_chunk']('reasoning', 'Second thought.')
        kwargs['on_chunk']('content', 'Answer.')
        return {'text': 'Answer.', 'tool_calls': []}

    monkeypatch.setattr('isycode.tui.provider_complete', complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await app._run_chat('Think quickly.')
            await pilot.pause()
            blocks = list(app.query(ThoughtBlock))
            assert len(blocks) == 1
            assert plain_text(blocks[0]._body) == 'First thought. Second thought.'
            assert blocks[0].collapsed

    with capsys.disabled():
        asyncio.run(scenario())


def test_completed_answers_remain_separate_after_later_user_turns(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    answers = ["Answer alpha.", "Answer beta.", "Answer gamma."]
    requests = []

    async def complete(provider, messages, **kwargs):
        prompt = messages[-1]["content"]
        requests.append(prompt)
        answer = answers[len(requests) - 1]
        kwargs["on_chunk"]("content", answer)
        return {"text": answer, "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt-input")
            questions = ["Question alpha?", "Question beta?", "Question gamma?"]
            for question in questions:
                prompt.load_text(question)
                app._accept_prompt(prompt, prompt.text)
                for _ in range(100):
                    await pilot.pause(0.02)
                    if app._foreground_lane().loop_task is None:
                        break
                assert app._foreground_lane().loop_task is None

            visible = [widget for widget in app.query_one(ChatArea).query(SelectableText)]
            user_text = [widget.selection_text for widget in visible if widget.has_class("user-turn")]
            assistant_text = [widget.selection_text for widget in visible
                              if not widget.has_class("user-turn")
                              and widget.selection_text in answers]
            assert user_text == questions
            assert assistant_text == answers
            assert requests == user_text
            assert [(item["role"], item["content"]) for item in app._history] == [
                ("user", "Question alpha?"), ("assistant", answers[0]),
                ("user", "Question beta?"), ("assistant", answers[1]),
                ("user", "Question gamma?"), ("assistant", answers[2]),
            ]

    with capsys.disabled():
        asyncio.run(scenario())


def test_reasoning_stream_batches_expensive_thought_paints(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    chunks = [f"reasoning-{index:03d} " + ("detail " * 40) for index in range(80)]

    async def complete(provider, messages, **kwargs):
        for chunk in chunks:
            kwargs["on_chunk"]("reasoning", chunk)
            await asyncio.sleep(0.001)
        kwargs["on_chunk"]("content", "Done.")
        return {"text": "Done.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)
    paints = 0
    original_paint = ThoughtBlock._paint_preview

    def count_paints(block):
        nonlocal paints
        paints += 1
        return original_paint(block)

    monkeypatch.setattr(ThoughtBlock, "_paint_preview", count_paints)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app._run_chat("Explain this carefully.")
            await pilot.pause()
            block = app.query_one(ThoughtBlock)
            assert block._full_text == "".join(chunks)
            assert block.collapsed
            assert paints < len(chunks) // 2

    with capsys.disabled():
        asyncio.run(scenario())


def test_reasoning_stream_reuses_block_after_switching_lanes(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    first_chunk, continue_stream = asyncio.Event(), asyncio.Event()

    async def complete(provider, messages, **kwargs):
        kwargs["on_chunk"]("reasoning", "First thought. ")
        kwargs["on_chunk"]("content", "First content. ")
        first_chunk.set()
        await continue_stream.wait()
        kwargs["on_chunk"]("reasoning", "Second thought.")
        kwargs["on_chunk"]("content", "Second content.")
        return {"text": "First content. Second content.", "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            first = app._foreground_lane()
            app._start_background_turn(first, "Explain this.")
            await first_chunk.wait()

            second = ConversationLane("memory-2")
            app._lanes[second.key] = second
            app._show_lane(second)
            await pilot.pause()
            app._show_lane(first)
            await pilot.pause()
            continue_stream.set()
            await first.loop_task
            await pilot.pause()

            blocks = list(app.query(ThoughtBlock))
            assert len(blocks) == 1
            assert blocks[0]._full_text == "First thought. Second thought."
            assert blocks[0].collapsed
            content = [widget.selection_text for widget in app.query_one(ChatArea).query(SelectableText)]
            assert "First content. Second content." in content

    with capsys.disabled():
        asyncio.run(scenario())


def test_content_burst_coalesces_markdown_paints_and_flushes_exact_answer(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    chunks = [f"chunk-{index:03d} " + ("sample text " * 8) for index in range(96)]
    answer = "".join(chunks)

    async def complete(provider, messages, **kwargs):
        for chunk in chunks:
            kwargs["on_chunk"]("content", chunk)
        return {"text": answer, "tool_calls": []}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)
    from isycode.tui_app_chat import RichMarkdown as OriginalMarkdown
    markdown_calls = 0

    def count_markdown(*args, **kwargs):
        nonlocal markdown_calls
        markdown_calls += 1
        return OriginalMarkdown(*args, **kwargs)

    monkeypatch.setattr("isycode.tui_app_chat.RichMarkdown", count_markdown)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app._run_chat("Render this burst.")
            await pilot.pause()
            rendered = [widget.selection_text for widget in app.query_one(ChatArea).query(SelectableText)]
            assert answer in rendered
            assert app._history[-1]["content"] == answer.strip()
            assert markdown_calls < len(chunks) // 2

    with capsys.disabled():
        asyncio.run(scenario())


@pytest.mark.parametrize("ending", ["failure", "cancel"])
def test_content_flushes_latest_partial_on_failure_and_cancel(tmp_path, monkeypatch, capsys, ending):
    configure(tmp_path, monkeypatch)
    started = asyncio.Event()
    partial = "Latest partial text, fully selectable."
    attempts = 0

    async def complete(provider, messages, **kwargs):
        if ending == "cancel":
            kwargs["on_chunk"]("content", partial[:12])
            kwargs["on_chunk"]("content", partial[12:])
            started.set()
            await asyncio.Event().wait()
        nonlocal attempts
        attempts += 1
        latest = partial if attempts == 4 else f"Discarded retry {attempts}."
        kwargs["on_chunk"]("content", latest[:12])
        kwargs["on_chunk"]("content", latest[12:])
        from isycode.streaming import StreamError
        raise StreamError("synthetic stream failure")

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def no_retry_delay(_delay):
        return None

    monkeypatch.setattr("isycode.continuity_recovery.wait_fixed", no_retry_delay)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            task = asyncio.create_task(app._run_chat("Keep the partial text."))
            if ending == "cancel":
                await asyncio.wait_for(started.wait(), 5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
            await pilot.pause()
            if ending == "failure":
                assert attempts == 4
                assert app._interrupted_turn.partial_text == partial
            rendered = [widget.selection_text for widget in app.query_one(ChatArea).query(SelectableText)]
            assert partial in rendered
            assert app._history == []

    with capsys.disabled():
        asyncio.run(scenario())
