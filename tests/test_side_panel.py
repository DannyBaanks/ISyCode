"""Right rail: integrations read as green/red switches, sections fold, the command bar keeps its labels."""
import asyncio

from isycode.contracts import CatalogSnapshot
from isycode.tui import GREEN, RED, TUIApp, plain_text, switch_row
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


def test_mcp_snapshot_counts_healthy_services():
    snapshot = CatalogSnapshot(True, [{"name": "files", "status": "connected"},
                                      {"name": "web", "status": "connected", "has_error": True}],
                               "ready", "")
    body, title = TUIApp._format_mcp_snapshot(snapshot)
    assert title == "MCPs · 1/2 on"
    assert "files" in body.plain and "service reports an error" in body.plain


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
            section.collapsed = False
            await pilot.pause()
            assert not section.collapsed
            section.collapsed = True
            await pilot.pause()
            assert section.collapsed

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
            app.query_one("#rail-lsp").collapsed = False
            await pilot.pause()
            await pilot.click("#lsp-install-hint")
            await pilot.pause()
            text = plain_text(app.query_one("#lsp-install-note"))
            assert "does not download" in text
            assert "Nothing was installed" in text
            assert "go install golang.org/x/tools/gopls@latest" in text
            assert "sandbox cannot launch it" in text
            assert "ON" not in plain_text(app.query_one("#lsp-status"))

    with capsys.disabled():
        asyncio.run(scenario())
