"""Tests for Codex-style local file hyperlinks, multi-tab sidebar viewer, and Files N."""
from __future__ import annotations

import asyncio
from pathlib import Path

from rich.text import Text
from textual.widgets import Button, OptionList, Static, Tree

from isycode.file_preview import FilePreviewScreen
from isycode.localization import configure_locale
from isycode.sidebar_files import (
    ConversationFileTracker,
    FileLink,
    SidebarTabManager,
    SourceLocation,
    extract_file_links_from_markdown,
    format_conversation_file_row,
    parse_local_file_link,
    truncate_middle_path,
)
from isycode.terminal_links import classify_link, linkify_markdown, rich_markdown
from isycode.tui import TUIApp, plain_text
from isycode.tui_copy import CopyMenuScreen, CopyTextArea, selectable_markdown
from isycode.tui_widgets import ChatArea, SelectableText, SidePanel
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure


# ── Pure unit tests: parsing, truncation, tracker, tab manager ───────────────


def test_parse_local_file_link_handles_uris_locations_and_rejects_unsafe(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    uri = parse_local_file_link(f"file://{(root / 'saludar.mb').as_posix()}#L12C4")
    assert uri is not None
    assert uri.path == str((root / "saludar.mb"))
    assert uri.location == SourceLocation(line=12, column=4)

    rel = parse_local_file_link("src/app.py:42:7", root=root)
    assert rel is not None
    assert rel.path == str(root / "src" / "app.py")
    assert rel.location == SourceLocation(line=42, column=7)

    range_ref = parse_local_file_link("docs/GUIA.md#L10-L20", root=root)
    assert range_ref is not None
    assert range_ref.path == str(root / "docs" / "GUIA.md")
    assert range_ref.location == SourceLocation(line=10, column=1)

    md_anchor = parse_local_file_link("GUIA.md#como-ejecutarlo", root=root)
    assert md_anchor is not None
    assert md_anchor.path == str(root / "GUIA.md")
    assert md_anchor.location is None

    makefile = parse_local_file_link("Makefile", root=root)
    assert makefile is not None and makefile.name == "Makefile"

    win = parse_local_file_link("file:///C:/repo/main.py#L9")
    assert win is not None and win.path == "C:/repo/main.py" and win.location == SourceLocation(9, 1)

    # Reject web URLs, remote file hosts, queries, control chars, trailing slash, prose
    for bad in (
        "https://example.com/a.py",
        "http://localhost:8000/a.py",
        "file://remote.host/etc/passwd",
        "src/app.py?raw=1",
        "src/app.py\x1b[31m",
        "src/folder/",
        "#section-only",
        "3.14",
        "plainword",
    ):
        assert parse_local_file_link(bad, root=root) is None, bad


def test_classify_link_and_markdown_autolinking_keep_urls_and_code_safe(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    assert classify_link("https://example.com/x", root=root) == ("external", "https://example.com/x")
    kind, target = classify_link("src/app.py:15", root=root)
    assert kind == "file" and target.location == SourceLocation(15, 1)

    linked = linkify_markdown("Open src/app.py:15 and `ignored/code.py:2` and https://example.com/a.py.")
    assert "[src/app.py:15](src/app.py:15)" in linked
    assert "`ignored/code.py:2`" in linked
    assert "[https://example.com/a.py](https://example.com/a.py)." in linked
    assert "[[" not in linked

    rendered = selectable_markdown(rich_markdown("See [saludar.mb](saludar.mb) and GUIA.md", root=root))
    assert rendered.plain.rstrip("\n") == "See saludar.mb and GUIA.md"
    links = [span.style for span in rendered.spans if "link " in str(span.style)]
    assert any("saludar.mb" in str(s) for s in links)
    assert any("GUIA.md" in str(s) for s in links)


def test_truncate_middle_path_and_conversation_file_row(tmp_path):
    long_dir = "/home/danny/Development/ISyCo/vm_malbolge/evidence/g5b_flag_return_v14_saludar"
    truncated = truncate_middle_path(long_dir, 30)
    assert len(truncated) <= 30
    assert "..." in truncated
    assert truncated.startswith("/home/")
    assert truncated.endswith("saludar")

    root = tmp_path / "repo"
    link = FileLink(path=str(root / "a" / "b" / "c" / "deep" / "saludar.mb"), location=SourceLocation(7))
    row = format_conversation_file_row(link, root=root, width=32)
    assert row.plain.startswith("· saludar.mb:7")
    assert len(row.plain) <= 32

    ascii_row = format_conversation_file_row(link, root=root, width=32, ascii_only=True)
    assert ascii_row.plain.startswith("- saludar.mb:7")


def test_conversation_file_tracker_deduplicates_and_promotes_newest(tmp_path):
    root = tmp_path / "repo"
    tracker = ConversationFileTracker()
    assert tracker.record_markdown(
        "Checked [a.py](src/a.py:12) and [b.md](docs/b.md).", root=root
    )
    assert [e.name for e in tracker.entries] == ["a.py", "b.md"]
    assert tracker.entries[0].location == SourceLocation(12, 1)

    # Promoting b.md moves it to top; re-recording a.py without location preserves line 12
    assert tracker.record_path("docs/b.md", root=root)
    assert [e.name for e in tracker.entries] == ["b.md", "a.py"]
    assert tracker.record_path("src/a.py", root=root)
    assert [e.name for e in tracker.entries] == ["a.py", "b.md"]
    assert tracker.entries[0].location == SourceLocation(12, 1)

    # Extracting from markdown ignores fenced code blocks
    extracted = extract_file_links_from_markdown("```\nsecret/inside.py\n```\nOutside [ok.py](ok.py)", root=root)
    assert [e.name for e in extracted] == ["ok.py"]


def test_sidebar_tab_manager_lifecycle_and_overflow():
    mgr = SidebarTabManager(max_tabs=12)
    tabs = []
    for i in range(6):
        tabs.append(
            mgr.open_or_update(
                path=f"/repo/module_{i}.py",
                title=f"module_{i}.py",
                relative=f"module_{i}.py",
                content=f"x = {i}\n",
                size_bytes=6,
                receipt_id=f"rcpt-{i}",
                is_markdown=False,
            )
        )
    assert len(mgr.tabs) == 6
    assert mgr.active_id == tabs[-1].tab_id

    # Re-opening existing path updates in-place instead of duplicating
    updated = mgr.open_or_update(
        path="/repo/module_1.py",
        title="module_1.py",
        relative="module_1.py",
        content="x = 99\n",
        size_bytes=7,
        receipt_id="rcpt-new",
        is_markdown=False,
        location=SourceLocation(1, 3),
    )
    assert len(mgr.tabs) == 6
    assert updated.tab_id == tabs[1].tab_id
    assert updated.location == SourceLocation(1, 3)

    # Overflow window on narrow width
    visible, can_left, can_right = mgr.visible_window(28)
    assert len(visible) < 6
    assert can_left or can_right

    # Closing active tab activates neighbor
    next_tab = mgr.close(tabs[1].tab_id)
    assert next_tab is not None
    assert len(mgr.tabs) == 5


# ── TUI integration tests ────────────────────────────────────────────────────


def test_chat_hyperlink_opens_sidebar_tabs_jumps_to_line_and_navigates_markdown(
    tmp_path, monkeypatch, capsys
):
    root = configure(tmp_path, monkeypatch)
    code_file = root / "saludar.py"
    code_file.write_text("line1 = 1\nline2 = 2\ndef saludar():\n    return 'Hola'\n", encoding="utf-8")
    guide_file = root / "GUIA.md"
    guide_file.write_text(
        "# Guía\n\nVer [saludar.py](saludar.py#L3) para la implementación.\n",
        encoding="utf-8",
    )

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await app.wait_for_ready()
            await pilot.pause()

            # Mount an assistant turn containing clickable local file links
            app._dismiss_idle()
            chat = app.query_one(ChatArea)
            md = f"Mira [saludar.py](file://{code_file.as_posix()}#L3) y [GUIA.md](GUIA.md)."
            msg = SelectableText(rich_markdown(md, root=root), selection_text=md, classes="assistant-turn")
            await chat.mount(msg)
            app._record_conversation_files(md)
            await pilot.pause()

            # Click the first local file link ("saludar.py" starts at x=5 on row 0)
            await pilot.click(msg, offset=(6, 0))
            for _ in range(40):
                if app._rail_view == "doc" and app._sidebar_tabs_state().active_tab is not None:
                    break
                await pilot.pause(0.05)

            assert app.query_one(SidePanel).display is True
            assert app._rail_view == "doc"
            assert app.query_one("#doc-view").display is True
            assert app.query_one("#doc-code").display is True
            assert app.query_one("#doc-markdown-scroll").display is False

            editor = app.query_one("#doc-code", CopyTextArea)
            assert editor.read_only is True
            assert "def saludar():" in editor.text
            assert editor.cursor_location[0] == 2  # 1-based line 3 -> 0-based row 2
            assert "L3" in plain_text(app.query_one("#doc-meta"))

            # Click the Markdown link ("GUIA.md" starts after "Mira saludar.py y " -> x=19)
            await pilot.click(msg, offset=(20, 0))
            for _ in range(40):
                tab = app._sidebar_tabs_state().active_tab
                if tab is not None and tab.title == "GUIA.md":
                    break
                await pilot.pause(0.05)

            assert app._sidebar_tabs_state().active_tab.title == "GUIA.md"
            assert len(app._sidebar_tabs_state().tabs) == 2
            assert app.query_one("#rail-doc-strip").display is True
            assert app.query_one("#doc-markdown-scroll").display is True
            assert app.query_one("#doc-code").display is False
            assert "Guía" in app.query_one("#doc-markdown", SelectableText).render().plain

            # Clicking a link inside the Markdown sidebar tab switches to saludar.py
            md_doc = app.query_one("#doc-markdown", SelectableText)
            # Row 0 is "Guía", row 1 blank, row 2 is "Ver saludar.py para la implementación."
            await pilot.click(md_doc, offset=(6, 2))
            for _ in range(40):
                tab = app._sidebar_tabs_state().active_tab
                if tab is not None and tab.title == "saludar.py":
                    break
                await pilot.pause(0.05)
            assert app._sidebar_tabs_state().active_tab.title == "saludar.py"

            # Expand button still opens full FilePreviewScreen modal
            await app.on_button_pressed(Button.Pressed(app.query_one("#doc-expand-modal", Button)))
            for _ in range(40):
                if isinstance(app.screen, FilePreviewScreen) and app.screen.is_mounted:
                    break
                await pilot.pause(0.05)
            assert isinstance(app.screen, FilePreviewScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, FilePreviewScreen)

            # Escape inside #doc-view backs out to #files-view
            editor.focus()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app._rail_view == "files"
            assert app.query_one("#files-view").display is True

            # Closing all tabs hides #rail-doc-strip
            for tab in list(app._sidebar_tabs_state().tabs):
                app._close_sidebar_tab(tab.tab_id)
            await pilot.pause()
            assert app.query_one("#rail-doc-strip").display is False

            # Drag-selecting over a file link must NOT open a sidebar tab
            await pilot.mouse_down(msg, offset=(5, 0))
            await pilot.mouse_up(msg, offset=(12, 0))
            await pilot.pause(0.15)
            assert len(app._sidebar_tabs_state().tabs) == 0

    with capsys.disabled():
        asyncio.run(scenario())


def test_double_click_keeps_copy_menu_and_security_mode_fails_closed(tmp_path, monkeypatch, capsys):
    project = tmp_path / "secproj"
    project.mkdir()
    secret = project / "secret.py"
    secret.write_text("TOKEN = 'nope'\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside secret\n", encoding="utf-8")

    monkeypatch.chdir(project)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="security", locale="en")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await app.wait_for_ready()
            await pilot.pause()

            # Security mode without workspace.files.read grant MUST deny fail-closed
            opened = await app._open_sidebar_document(str(secret))
            assert opened is False
            assert len(app._sidebar_tabs_state().tabs) == 0

            # Even with workspace.files.read granted for project, outside path MUST fail closed
            WorkspaceAuthority(project).set_grant(
                "workspace.files.read", enabled=True, path_prefixes=[str(project)]
            )
            outside_opened = await app._open_sidebar_document(str(outside))
            assert outside_opened is False
            assert len(app._sidebar_tabs_state().tabs) == 0

            # Double-click on SelectableText with a link still opens CopyMenuScreen
            app._dismiss_idle()
            chat = app.query_one(ChatArea)
            md = f"Check [secret.py](secret.py) here."
            msg = SelectableText(rich_markdown(md, root=project), selection_text=md)
            await chat.mount(msg)
            await pilot.pause()
            await pilot.click(msg, offset=(1, 0), times=2)
            for _ in range(30):
                if isinstance(app.screen, CopyMenuScreen):
                    break
                await pilot.pause(0.05)
            assert isinstance(app.screen, CopyMenuScreen)
            await pilot.press("escape")
            await pilot.pause()

    with capsys.disabled():
        asyncio.run(scenario())


def test_files_n_chooser_new_side_chat_sober_tree_and_compact_spanish_layout(
    tmp_path, monkeypatch, capsys
):
    root = configure(tmp_path, monkeypatch)
    sub = root / "pkg" / "deep"
    sub.mkdir(parents=True)
    alpha = sub / "alpha.py"
    alpha.write_text("print('alpha')\n", encoding="utf-8")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.wait_for_ready()
            await pilot.pause()

            # Recording a file updates Files N list
            app._record_conversation_files(f"Edited [alpha.py](pkg/deep/alpha.py:1)")
            await pilot.pause()

            # Clicking '+' opens sidebar chooser with Files N visible
            await app.on_button_pressed(Button.Pressed(app.query_one("#rail-tab-add", Button)))
            await pilot.pause()
            assert app.query_one("#files-view").display is True
            assert app.query_one("#sidebar-chooser").display is True
            assert "Files 1" in plain_text(app.query_one("#conversation-files-header"))
            conv_list = app.query_one("#conversation-files-list", OptionList)
            assert conv_list.display is True and conv_list.option_count == 1

            # Selecting the Files N row opens alpha.py in a sidebar tab
            app._open_conversation_file_at(0)
            for _ in range(40):
                tab = app._sidebar_tabs_state().active_tab
                if tab is not None and tab.title == "alpha.py":
                    break
                await pilot.pause(0.05)
            assert app._sidebar_tabs_state().active_tab.title == "alpha.py"

            # Explorer tree has sober glyphs (no 📁/📄 emojis)
            app._set_rail_view("files")
            await app._load_directory(str(root))
            tree = app.query_one("#workspace-tree", Tree)
            assert "📁" not in str(tree.root.label)
            assert all("📄" not in str(child.label) and "📁" not in str(child.label) for child in tree.root.children)

            # Spanish locale repaint updates all new sidebar chrome cleanly
            configure_locale("es")
            app._apply_locale_chrome()
            await pilot.pause()
            assert "Abrir en barra lateral" in plain_text(app.query_one("#sidebar-chooser-title"))
            assert "Archivos 1" in plain_text(app.query_one("#conversation-files-header"))
            assert "enter abrir" in plain_text(app.query_one("#rail-footer-hint"))
            configure_locale("en")

            # '+ New side chat' starts a fresh conversation and clears Files N
            await app.on_button_pressed(Button.Pressed(app.query_one("#sidebar-new-chat", Button)))
            await pilot.pause()
            assert len(app._conversation_files_state()) == 0
            assert app.query_one("#conversation-files-list").display is False

    with capsys.disabled():
        asyncio.run(scenario())
