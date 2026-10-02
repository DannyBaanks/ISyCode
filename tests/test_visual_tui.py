from isycode.tui import plain_text
import asyncio
import json

from rich.cells import cell_len
from textual.widgets import Button, Collapsible, Static

from isycode.tui import Banner, ChatArea, SidePanel, TUIApp, TailscaleConfirmScreen
from test_daily_tui import configure


def test_narrow_sidebar_files_tab_is_visible_and_clickable(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert not app.query_one(SidePanel).display
            app.action_toggle_sidebar()
            await pilot.pause()
            files = app.query_one('#show-files', Button)
            tabs = app.query_one('#rail-tabs')
            assert tabs.region.contains_region(files.region)
            await pilot.resize_terminal(90, 26)
            await pilot.pause()
            assert app.query_one(SidePanel).display
            await pilot.click('#show-files')
            await pilot.pause()
            assert app.query_one('#files-view').display
            assert not app.query_one('#overview-view').display

    with capsys.disabled():
        asyncio.run(scenario())


def test_long_workspace_header_keeps_status_and_path_end(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    project = root / ('workspace-' + 'x' * 90) / '日本語-project'
    project.mkdir(parents=True)
    monkeypatch.chdir(project)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            if isinstance(app.screen, TailscaleConfirmScreen):
                await pilot.press("escape")
                await pilot.pause()
            banner = app.query_one(Banner)
            header = plain_text(banner)
            assert cell_len(header) <= banner.content_size.width
            assert '● workspace' in header and '日本語-project' in header
            app.action_toggle_sidebar()
            await pilot.pause()
            assert cell_len(plain_text(banner)) <= app.query_one(SidePanel).region.x - 1
            assert '● workspace' in plain_text(banner)

    with capsys.disabled():
        asyncio.run(scenario())


def test_settings_groups_integrations_and_returns_without_actions(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._open_settings_menu()
            entry = next(e for e in app._menu_entries if e['kind'] == 'integrations_open')
            assert not any(e['kind'] == 'bridge_settings' for e in app._menu_entries)
            app._select_menu_entry(entry)
            assert any(e['kind'] == 'bridge_settings' for e in app._menu_entries)
            assert any(e['kind'] == 'mobile_host_status' for e in app._menu_entries)
            app._select_menu_entry(next(e for e in app._menu_entries if e['kind'] == 'settings_back'))
            assert app._menu_mode == 'settings'
            assert not app._bridge_enabled

    with capsys.disabled():
        asyncio.run(scenario())


def test_owned_read_keeps_receipt_in_expandable_detail(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    (root / 'file.py').write_text('value = 1\n')

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            _, result = await app._dispatch_chat_tool({'id': 'read', 'function': {
                'name': 'workspace_read', 'arguments': json.dumps({'path': 'file.py'})}})
            await pilot.pause()
            assert 'value = 1' in result
            detail = app.query_one('.tool-receipt', Collapsible)
            assert detail.collapsed
            assert not any('rcpt_' in app._render_searchable_text(row)
                           for row in app.query_one(ChatArea).children if isinstance(row, Static))
            from unittest.mock import Mock
            app._search_console('rcpt_', Mock())
            await pilot.pause()
            assert not detail.collapsed
            assert any('rcpt_' in app._render_searchable_text(row) for row in detail.query(Static))

    with capsys.disabled():
        asyncio.run(scenario())


def test_composer_help_is_visible_without_covering_input_or_navigation(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            hint = app.query_one('#composer-hint')
            prompt = app.query_one('#prompt-input')
            bar = app.query_one('#command-bar')
            assert app.screen.region.contains_region(hint.region)
            assert not hint.region.overlaps(prompt.region)
            assert not hint.region.overlaps(bar.region)

    with capsys.disabled():
        asyncio.run(scenario())
