"""The local work list is not a multi-agent supervisor."""
import asyncio
import json
from datetime import datetime

import pytest

from isycode.chat_sessions import ChatSessionStore
from isycode.work_list import fit_heading
from isycode.session_owner import ChatSessionOwner
from isycode.tui import TUIApp, plain_text
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure


def test_owned_messages_get_real_local_time_and_export_keeps_it(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'project'; root.mkdir()
    auth = WorkspaceAuthority(root); auth.set_mode('classic')
    owner = ChatSessionOwner(root, auth, tmp_path / 'sessions')
    before = datetime.now().astimezone()
    outcome, sid = owner.record(None, 'user', 'hello')
    after = datetime.now().astimezone()
    assert outcome.decision == 'ALLOW'
    message = owner.resume(sid)[1].messages[0]
    recorded = datetime.fromisoformat(message['sent_at'])
    assert before.replace(microsecond=0) <= recorded <= after
    exported = json.loads(owner.export(sid)[1])
    assert exported['messages'][0]['sent_at'] == message['sent_at']
    imported = owner.store.parse_import(json.dumps(exported))
    assert imported.messages[0]['sent_at'] == message['sent_at']
    legacy = owner.store.create('old')
    legacy.messages = [{'role': 'user', 'content': 'old'}]
    owner.store.save(legacy)
    assert 'sent_at' not in owner.store.load(legacy.session_id).messages[0]
    stamp = '2026-10-02T17:06:00-06:00'
    kept, kept_id = owner.record(None, 'user', 'stamped', sent_at=stamp)
    assert kept.decision == 'ALLOW'
    assert owner.resume(kept_id)[1].messages[0]['sent_at'] == stamp
    replaced, replaced_id = owner.record(None, 'user', 'naive', sent_at='2026-10-02T17:06:00')
    assert replaced.decision == 'ALLOW'
    naive = owner.resume(replaced_id)[1].messages[0]['sent_at']
    assert naive != '2026-10-02T17:06:00'
    assert datetime.fromisoformat(naive).tzinfo is not None


def test_work_heading_keeps_the_counts_when_the_path_is_long():
    path = '/home/danny/Development/ISyCo Git/a-very-long-workspace-name'
    heading = fit_heading(path, '2 idle', 36)
    assert heading.endswith('2 idle')
    assert '…' in heading
    assert fit_heading(path, '2 idle', 200) == f'{path}    2 idle'


def test_sessions_panel_switches_here_and_blocks_during_generation(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            owner = app._chat_session_owner
            _, first = owner.record(None, 'user', 'First task')
            _, second = owner.record(None, 'user', 'Second task')
            await app._show_chat_sessions()
            await pilot.pause()
            panel = app.query_one('#work-list')
            assert panel.display and not app._menu_mode
            assert not app.query_one('#chat').display
            assert app.screen.id == '_default'
            labels = ' '.join(str(option.prompt) for option in app.query_one('#work-conversations')._options)
            assert 'Idle' in labels and 'First task' in labels and 'Second task' in labels
            assert 'now' in labels
            await app._resume_chat_session(first)
            assert app._active_chat_session_id == first
            stop = asyncio.Event()
            task = asyncio.create_task(stop.wait()); app._loop_task = task
            try:
                await app._resume_chat_session(second)
                assert app._active_chat_session_id == first
                app._start_new_conversation()
                assert app._active_chat_session_id == first
                assert app._conversation_status() == 'generating'
            finally:
                task.cancel(); await asyncio.gather(task, return_exceptions=True); app._loop_task = None
            await app._resume_chat_session(second)
            assert app._active_chat_session_id == second
            app._start_new_conversation()
            await pilot.pause()
            assert app._active_chat_session_id not in {first, second, None}
            assert app._conversation_status() == 'idle'
            assert 'sent_at' not in json.dumps(app._history)
    with capsys.disabled():
        asyncio.run(scenario())


@pytest.mark.parametrize("size", [(80, 24), (120, 40), (160, 48)])
def test_session_toolbar_text_remains_visible_and_all_controls_fit(tmp_path, monkeypatch, size):
    from textual.widgets import Button
    from isycode.tui import SidePanel
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            if not app.query_one(SidePanel).display:
                app.action_toggle_sidebar()
            await app._show_chat_sessions()
            await pilot.pause()
            board = app.query_one("#work-list")
            buttons = [board.query_one("#" + name, Button) for name in ("work-new", "work-refresh", "work-bridge", "work-hide")]
            for button in buttons:
                button.focus()
                await pilot.hover(button)
                await pilot.pause()
                assert button.content_size.height == 1
                assert button.styles.border_top[0] == ""
                assert button.styles.border_bottom[0] == ""
                assert board.region.contains_region(button.region)
                assert str(button.label).strip()
            assert all(not left.region.overlaps(right.region) for left, right in zip(buttons, buttons[1:]))
    asyncio.run(scenario())


def test_sessions_filters_and_details_use_real_selected_row(tmp_path, monkeypatch):
    from isycode.work_list import WorkList
    configure(tmp_path, monkeypatch)
    # Patch before mount: its timer captures the bound callback at startup.
    monkeypatch.setattr(TUIApp, "_paint_work_status", lambda self: None)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(160, 48)) as pilot:
            # This component fixture supplies its own rows, independently of
            # the application's periodic owner-backed session refresh.
            monkeypatch.setattr(app, '_paint_work_status', lambda: None)
            await pilot.pause()
            board = app.query_one(WorkList)
            board.display = True
            board.show_rows([
                {"id": "a", "title": "Read", "status": "idle", "model": "z-ai/glm-5.3", "provider": "nvidia", "detail": "Full last message", "workspace": "Project"},
                {"id": "b", "title": "Run", "status": "generating"},
            ])
            listing = board.query_one("#work-conversations")
            listing.highlighted = next(index for index, option in enumerate(listing._options) if option.id == "a")
            await pilot.pause()
            text = str(board.query_one("#work-details").render())
            assert "GLM 5.3" in text and "Full last message" in text
            await pilot.click("#work-filter-generating")
            await pilot.pause()
            assert listing.option_count == 2
            assert listing.get_option_at_index(1).id == "b"
    asyncio.run(scenario())


def test_sessions_first_click_previews_second_opens_and_arrows_select(tmp_path, monkeypatch):
    from isycode.work_list import WorkList
    configure(tmp_path, monkeypatch)
    # Patch before mount: its timer captures the bound callback at startup.
    monkeypatch.setattr(TUIApp, "_paint_work_status", lambda self: None)
    opened = []
    async def resume(self, session_id):
        opened.append(session_id)
    monkeypatch.setattr(TUIApp, "_resume_chat_session", resume)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(160, 48)) as pilot:
            # This component fixture supplies its own rows, independently of
            # the application's periodic owner-backed session refresh.
            monkeypatch.setattr(app, '_paint_work_status', lambda: None)
            await pilot.pause()
            board = app.query_one(WorkList)
            board.display = True
            board.show_rows([
                {"id": "a", "title": "First", "status": "idle", "detail": "First details"},
                {"id": "b", "title": "Second", "status": "idle", "detail": "Second details"},
            ])
            await pilot.pause()
            await pilot.click("#work-conversations", offset=(2, 1))
            await pilot.pause()
            assert opened == []
            assert "First details" in str(board.query_one("#work-details").render())
            await pilot.click("#work-conversations", offset=(2, 1))
            await pilot.pause()
            assert opened == ["a"]
            await pilot.press("down")
            await pilot.pause()
            assert "Second details" in str(board.query_one("#work-details").render())
            assert opened == ["a"]
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert opened == ["a", "b"]
    asyncio.run(scenario())


def test_deferred_resize_uses_latest_selected_row(tmp_path,monkeypatch):
    from isycode.work_list import WorkList
    configure(tmp_path,monkeypatch)
    async def scenario():
        app=TUIApp()
        async with app.run_test(size=(160,48)) as pilot:
            # This component fixture supplies its own rows, independently of
            # the application's periodic owner-backed session refresh.
            monkeypatch.setattr(app, '_paint_work_status', lambda: None)
            await pilot.pause()
            await pilot.pause()
            board=app.query_one(WorkList)
            board.display=True
            await pilot.pause()
            board._selected_row={'title':'old','detail':'old detail'}
            board.on_resize()
            board._selected_row={'title':'latest','detail':'latest detail'}
            await pilot.pause()
            assert 'latest detail' in str(board.query_one('#work-details').render())
    asyncio.run(scenario())


def test_session_model_precedes_long_title_and_delete_click_does_not_open(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    # Patch before mount: its timer captures the bound callback at startup.
    monkeypatch.setattr(TUIApp, "_paint_work_status", lambda self: None)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            # This component fixture supplies its own rows, independently of
            # the application's periodic owner-backed session refresh.
            monkeypatch.setattr(app, '_paint_work_status', lambda: None)
            await pilot.pause()
            await pilot.pause()
            board = app.query_one('#work-list')
            board.display = True
            await pilot.pause()
            board.show_rows([{'id': 'saved-session', 'title': 'Long prompt ' * 40,
                             'model': 'z-ai/glm-5.3', 'provider': 'nvidia', 'status': 'idle'}])
            await pilot.pause()
            listing = board.query_one('#work-conversations')
            text = listing.get_option_at_index(1).prompt
            assert text.plain.index('GLM 5.3') < text.plain.index('Long prompt')
            assert text.plain.endswith('[×]')
            calls = []
            async def delete(sid, **kwargs):
                calls.append(sid)
            app._delete_chat_session = delete
            points = []
            for y in range(listing.size.height):
                for x in range(listing.size.width):
                    style = app.screen.get_style_at(listing.region.x + x, listing.region.y + y)
                    if style.meta.get('delete_session') == 'saved-session':
                        points.append((x, y))
            assert points, (listing.region, text.plain)
            await pilot.click('#work-conversations', offset=points[0])
            await pilot.pause()
            assert calls == ['saved-session']
            assert app._active_chat_session_id != 'saved-session'
            listing.highlighted = 1
            listing.focus()
            await pilot.press('ctrl+d')
            await pilot.pause()
            assert calls == ['saved-session', 'saved-session']
            app.query_one('#prompt-input').focus()
            await pilot.press('ctrl+d')
            assert calls == ['saved-session', 'saved-session']
    asyncio.run(scenario())


def test_delete_confirmation_removes_only_selected_session_without_recurring_grant(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            owner = app._chat_session_owner
            _, first = owner.record(None, 'user', 'Keep me')
            _, second = owner.record(None, 'user', 'Delete me')
            app._active_chat_session_id = first
            policy = WorkspaceAuthority(root).policy()
            confirmations = []
            async def confirm(screen):
                confirmations.append(screen.title_text)
                return False
            app._await_screen = confirm
            await app._delete_chat_session(second, allow_once=True)
            assert owner.store.load(second) is not None
            async def yes(screen):
                confirmations.append(screen.title_text)
                return True
            app._await_screen = yes
            await app._delete_chat_session(second, allow_once=True)
            await pilot.pause()
            with pytest.raises(FileNotFoundError):
                owner.store.load(second)
            assert owner.store.load(first) is not None
            assert app._active_chat_session_id == first
            assert WorkspaceAuthority(root).policy() == policy
            assert confirmations == ['Delete me', 'Delete me']
    asyncio.run(scenario())
