"""Right rail: integrations read as green/red switches, sections fold, the command bar keeps its labels."""
import asyncio

from isycode.contracts import CatalogSnapshot
from isycode.tui import GREEN, RED, TUIApp, plain_text, switch_row
from isycode.tui_widgets import BoxTitle
from isycode.tui_theme import status_phrase
from isycode.user_defaults import UserDefaultsStore


def _colours(text):
    return {str(span.style) for span in text.spans}


def test_switch_rows_are_green_when_on_and_red_when_off():
    on = switch_row(True, "pyright")
    off = switch_row(False, "pyright", "unsupported")
    assert any(GREEN in style for style in _colours(on))
    assert any(RED in style for style in _colours(off))
    assert "unsupported" in off.plain
    assert all(" on " not in style for style in _colours(on) | _colours(off))
    assert "ON" not in on.plain and "OFF" not in off.plain


def test_switch_row_states_are_distinguishable_without_color():
    marks = {
        "on": switch_row(True, "x").plain.split(" ")[0],
        "off": switch_row(False, "x").plain.split(" ")[0],
        "checking": switch_row(None, "x").plain.split(" ")[0],
        "inactive": switch_row(False, "x", inactive=True).plain.split(" ")[0],
    }
    # Every state carries a distinct leading mark, so a monochrome terminal or a
    # red-green colour-blind user can still tell ON from OFF (the rail shows no
    # "ON"/"OFF" text by design).
    assert len(set(marks.values())) == 4
    assert marks["on"] != marks["off"]


def _luminance(hex_color):
    hex_color = hex_color.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(hex_color[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    la, lb = _luminance(fg), _luminance(bg)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_palette_meets_wcag_aa_for_its_actual_uses():
    from isycode.tui_theme import ACCENT, BG, GREEN, MUTED, RED, TEXT, YELLOW
    # Body text must clear WCAG AA (4.5:1).
    for color in (TEXT, MUTED):
        assert _contrast(color, BG) >= 4.5, f"{color} on {BG} below 4.5:1"
    # Status/brand marks are large or non-text UI components: AA needs 3:1.
    for color in (GREEN, RED, YELLOW, ACCENT):
        assert _contrast(color, BG) >= 3.0, f"{color} on {BG} below 3:1"


def test_mcp_snapshot_counts_healthy_services():
    snapshot = CatalogSnapshot(True, [{"name": "files", "status": "connected"},
                                      {"name": "web", "status": "connected", "has_error": True}],
                               "ready", "")
    body, title = TUIApp._format_mcp_snapshot(snapshot)
    assert title == "MCPs · 1/2 On"
    assert "files" in body.plain and "Service Reports An Error" in body.plain
    assert "web" in body.plain


def test_status_chips_use_title_case_and_leave_names_alone():
    assert status_phrase("LSPs · 2 ready · 3 missing") == "LSPs · 2 Ready · 3 Missing"
    assert status_phrase("6 available") == "6 Available"
    assert status_phrase("not on PATH") == "Not On PATH"
    assert status_phrase("installed · sandbox unavailable") == "Installed · Sandbox Unavailable"
    assert status_phrase("MCPs · 1/2 on") == "MCPs · 1/2 On"
    skills = CatalogSnapshot(
        True, [{"name": "brainstorming", "origin": "bundled"}], "ready", "")
    _body, title = TUIApp._format_skill_snapshot(skills)
    assert title == "Skills · 1 Available"
    assert "1 Available" in _body.plain
    assert "Select One Below For Details" in _body.plain
    assert TUIApp._origin_tag("bundled") == "Bundled"
    assert TUIApp._origin_tag("/home/danny/skills") == "/home/danny/skills"
    assert TUIApp._origin_tag("verification-before-completion") == "verification-before-completion"


def test_command_bar_labels_survive_hover_and_sections_fold(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="security")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            button = app.query_one("#context-button")
            await pilot.hover("#context-button")
            await pilot.pause()
            # A bracketed label is markup in newer Textual and renders blank.
            assert "Context" in str(button.label) and "[" not in str(button.label)
            section = app.query_one("#rail-lsp")
            assert section.collapsed and section.title.startswith("LSPs")
            assert app.query_one("#rail-card")
            connections = app.query_one("#rail-connections")
            assert connections.collapsed and connections.title.startswith("Connections")
            assert app.query_one("#rail-gateway").parent.parent.id == "rail-connections"
            section.collapsed = False
            await pilot.pause()
            assert not section.collapsed
            section.collapsed = True
            await pilot.pause()
            assert section.collapsed

    with capsys.disabled():
        asyncio.run(scenario())


def test_second_click_opens_a_selected_row_and_tree_node(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="security")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app._set_rail_view("overview")
            await pilot.pause()
            section = app.query_one("#rail-mcp")
            title = section.query_one(BoxTitle)
            await pilot.click(title)
            await pilot.pause()
            assert section.collapsed
            await pilot.click(title, offset=(max(0, title.size.width - 2), 0))
            await pilot.pause()
            assert not section.collapsed
            connections = app.query_one("#rail-connections")
            connections.query_one(BoxTitle).focus()
            await pilot.press("space")
            await pilot.pause()
            assert not connections.collapsed
            skills = app.query_one("#rail-skills")
            skills.collapsed = False
            tree = app.query_one("#skills-tree")
            tree.display = True
            tree.root.expand()
            tree.root.remove_children()
            folder = tree.root.add("Folder", allow_expand=True)
            leaf = tree.root.add_leaf(
                "local-skill",
                data={"name": "local-skill", "origin": "workspace", "description": "A local note."},
            )
            await pilot.pause()
            assert folder._line >= 0 and leaf._line > folder._line

            def at(node):
                region = tree._get_label_region(node._line)
                assert region is not None
                # Past the ▶ icon. That icon still expands on one click.
                return (region.x + 3, region.y - tree.scroll_offset.y)

            await pilot.click(tree, offset=at(folder))
            await pilot.pause()
            assert tree.cursor_line == folder._line and not folder.is_expanded
            await pilot.click(tree, offset=at(folder))
            await pilot.pause()
            assert folder.is_expanded
            detail = app.query_one("#skill-detail")
            await pilot.click(tree, offset=at(leaf))
            await pilot.pause()
            assert tree.cursor_line == leaf._line and not detail.display
            await pilot.click(tree, offset=at(leaf))
            await pilot.pause()
            assert detail.display and "A local note." in plain_text(detail)
            arrow = tree._get_label_region(folder._line)
            await pilot.click(tree, offset=(arrow.x, arrow.y - tree.scroll_offset.y))
            await pilot.pause()
            assert not folder.is_expanded

    with capsys.disabled():
        asyncio.run(scenario())


def test_catalog_lists_missing_servers_that_discovery_skips(monkeypatch):
    import isycode.lsp as lsp
    monkeypatch.setattr(lsp.shutil, "which", lambda command: None)
    assert lsp.discover_servers() == []
    rows = lsp.language_server_catalog()
    by_id = {row["id"]: row for row in rows}
    assert {"pyright", "rust-analyzer", "gopls", "clangd"} <= set(by_id)
    assert all(row["state"] == "not_installed" for row in rows)
    assert by_id["pyright"]["install_hint"] == "npm install -g pyright"
    assert "go install" in by_id["gopls"]["install_hint"]


def test_install_commands_are_shown_and_nothing_is_launched(tmp_path, monkeypatch, capsys):
    import isycode.tui as tui_mod
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="security")
    monkeypatch.setattr(tui_mod, "language_server_catalog", lambda discovered=None: [
        {"id": "gopls", "label": "gopls", "state": "not_installed",
         "install_hint": "go install golang.org/x/tools/gopls@latest", "presence": "missing"},
        {"id": "rust-analyzer", "label": "rust-analyzer", "state": "installed_unavailable",
         "install_hint": "rustup component add rust-analyzer", "presence": "installed"},
    ])

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app.action_toggle_sidebar()
            await pilot.pause()
            app.query_one("#rail-lsp").collapsed = False
            await pilot.pause()
            await pilot.click("#lsp-install-hint")
            await pilot.pause()
            text = plain_text(app.query_one("#lsp-install-note"))
            assert "does not download" in text
            assert "Nothing was installed" in text
            assert "go install golang.org/x/tools/gopls@latest" in text
            assert "sandbox cannot launch it" in text
            note = app.query_one("#lsp-install-note")
            assert note.content_size.width > 0
            assert all(len(note.render_line(i).text) <= note.content_size.width
                       for i in range(note.content_size.height))
            assert "ON" not in plain_text(app.query_one("#lsp-status"))

    with capsys.disabled():
        asyncio.run(scenario())
