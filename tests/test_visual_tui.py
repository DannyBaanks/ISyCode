from isycode.tui import plain_text
import asyncio
import json
import os

from rich.cells import cell_len
from textual.widgets import Button, Collapsible as TextualCollapsible, Static

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
            assert ('● Classic' in header or '● Security' in header) and '日本語-project' in header
            app.action_toggle_sidebar()
            await pilot.pause()
            assert cell_len(plain_text(banner)) <= app.query_one(SidePanel).region.x - 1
            assert '● Classic' in plain_text(banner) or '● Security' in plain_text(banner)

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
            detail = app.query_one('.tool-receipt', TextualCollapsible)
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


def test_idle_board_landscape_is_aligned_and_provider_list_keeps_unwired_rows_quiet(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            widget = app.query_one("#idle-board")
            board = plain_text(widget)
            assert "LSPs" in board and "MCPs" in board and "Skills" in board
            assert "▀" in board
            assert "╱" not in board
            assert "|##|" not in board
            assert not list(app.query("#open-idle-art"))
            assert all(cell_len(line) <= widget.content_size.width for line in board.splitlines()), (
                widget.content_size.width,
                [(cell_len(line), line[:70]) for line in board.splitlines()
                 if cell_len(line) > widget.content_size.width],
            )
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            narrow = plain_text(widget)
            assert "▀" in narrow or "ISYCODE" in narrow
            assert "LSPs" in narrow
            assert "╱" not in narrow
            assert all(cell_len(line) <= widget.content_size.width for line in narrow.splitlines())
            app._open_provider_menu()
            assert app._menu_title == "Select provider"
            assert any(entry["kind"] == "section" and entry["label"] == "Popular"
                       for entry in app._menu_entries)
            assert any(entry["kind"] == "provider" and "xAI Grok" in entry["label"]
                       for entry in app._menu_entries)
            unwired = next(entry for entry in app._menu_entries
                           if entry["kind"] == "provider_unwired" and entry["value"] == "GitHub Copilot")
            before_provider = os.environ.get("ISYCODE_PROVIDER")
            app._select_menu_entry(unwired)
            assert app._menu_mode == "providers"
            assert os.environ.get("ISYCODE_PROVIDER") == before_provider
            chat = "\n".join(plain_text(widget) for widget in app.query_one(ChatArea).query(Static))
            assert "no transport" not in chat.casefold()
            assert "GitHub Copilot" not in chat
            assert app._activity_message == "No transport"
            detail = plain_text(app.query_one("#action-detail"))
            assert "GitHub Copilot" in detail
            assert "no transport" in detail.casefold()

    with capsys.disabled():
        asyncio.run(scenario())


def test_blocked_menu_choices_stay_out_of_the_chat(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            def chat_text():
                return "\n".join(plain_text(widget) for widget in app.query_one(ChatArea).query(Static))

            before = chat_text()
            app._select_menu_entry({
                "kind": "info",
                "label": "rust-analyzer · Installed Unavailable",
                "value": "",
                "detail": "Detected executable only; no safe LSP execution adapter is connected for this server.",
            })
            assert chat_text() == before
            assert app._activity_message == "Nothing ran"
            assert "Detected executable only" in plain_text(app.query_one("#action-detail"))
            app._select_menu_entry({
                "kind": "authority_toggle",
                "label": "Read workspace files",
                "value": "workspace_read",
                "enabled": True,
            })
            assert chat_text() == before
            assert app._activity_message == "Included in Classic"
            assert "Switch this workspace to Security" in plain_text(app.query_one("#action-detail"))

    with capsys.disabled():
        asyncio.run(scenario())


def test_image_failure_retries_the_question_as_text(tmp_path, monkeypatch, capsys):
    from isycode.image_attachments import record_image_result
    from isycode.streaming import StreamError
    configure(tmp_path, monkeypatch)
    png = __import__("base64").b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=")
    calls = []

    async def complete(provider, messages, **kwargs):
        user = next(item for item in messages if item.get("role") == "user")
        calls.append(user["content"])
        if isinstance(user["content"], list):
            raise StreamError("provider closed an incomplete completion stream")
        return {"text": "The question, as text.", "tool_calls": [],
                "usage": {"completion_tokens": 3}}

    monkeypatch.setattr("isycode.tui.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            label = app._image_attachments.capture("image/png", png)
            await app._run_chat(f"{label} puedes ver la imagen?")
            chat = "\n".join(plain_text(widget) for widget in app.query_one(ChatArea).query(Static))
            answer = app._history[-1]["content"]
        assert len(calls) == 2
        assert isinstance(calls[0], list)
        assert any(isinstance(part, dict) and part.get("type") == "image_url" for part in calls[0])
        assert isinstance(calls[1], str) and "image_url" not in calls[1]
        assert answer == "The question, as text."
        assert "Picture not accepted" in chat
        assert "stream failed before an answer" not in chat

    with capsys.disabled():
        asyncio.run(scenario())

    calls.clear()
    record_image_result("openai", "gpt-6-luna", False)

    async def blind():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            label = app._image_attachments.capture("image/png", png)
            await app._run_chat(f"{label} puedes ver la imagen?")
            chat = "\n".join(plain_text(widget) for widget in app.query_one(ChatArea).query(Static))
            answer = app._history[-1]["content"]
        assert len(calls) == 1
        assert isinstance(calls[0], str) and "image_url" not in calls[0]
        assert answer == "The question, as text."
        assert "Picture not sent" in chat

    with capsys.disabled():
        asyncio.run(blind())


def test_startup_splash_remains_in_chat_and_scrolls_away(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            board = app.query_one("#idle-board")
            assert app._idle_mounted()
            app._mount_user_turn("hola")
            await pilot.pause()
            assert app.query_one("#idle-board") is board
            assert board.has_class("startup-archived")
            assert not app._idle_mounted()
            assert app.query_one(ChatArea).scroll_y > 0

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
            from rich.cells import cell_len
            assert cell_len(hint.render().plain.splitlines()[0]) <= hint.content_size.width

    with capsys.disabled():
        asyncio.run(scenario())


def test_panoramic_header_fills_chat_and_leaves_composer_visible(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(200, 60)) as pilot:
            await pilot.pause()
            for width, height in [(200, 60), (120, 40), (80, 24), (200, 60)]:
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                board = app.query_one('#idle-board')
                lines = [line for line in plain_text(board).splitlines() if '▀' in line]
                assert lines
                assert all(line.count('▀') == board.content_size.width for line in lines)
                assert len(lines) <= 36
                if height == 60:
                    assert len(lines) == 36
                composer = app.query_one('#composer')
                chat = app.query_one(ChatArea)
                board_lines = plain_text(board).splitlines()
                assert composer.region.bottom <= height
                assert board.region.y + len(lines) <= composer.region.y
                assert board.region.y + len(board_lines) - 1 < composer.region.y
                lsp = next(index for index, line in enumerate(board_lines) if 'LSPs' in line)
                assert chat.region.y <= board.region.y + lsp < chat.region.bottom
            app.save_screenshot('/tmp/isycode-header-tui.svg')

    with capsys.disabled():
        asyncio.run(scenario())
