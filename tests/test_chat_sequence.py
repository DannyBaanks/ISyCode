from isycode.tui import plain_text
import asyncio
import json

from textual.widgets import Static

from isycode.tui import ChatArea, TUIApp, ThoughtBlock
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
            await pilot.pause()
            chat = app.query_one(ChatArea)
            assert abs(chat.scroll_y - chat.max_scroll_y) <= 1
            from unittest.mock import Mock
            app._search_console('Old searchable marker', Mock())
            await pilot.pause()
            before = chat.scroll_y
            assert before < chat.max_scroll_y
            app._append('Another new message.')
            await pilot.pause()
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
            try:
                assert len(plain_text(app.query_one(ThoughtBlock)._body).splitlines()) == 2
                assert abs(chat.scroll_y - chat.max_scroll_y) <= 1
            finally:
                continue_stream.set()
                await task
            await pilot.pause()
            assert abs(chat.scroll_y - chat.max_scroll_y) <= 1
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
