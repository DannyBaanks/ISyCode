"""Right rail: integrations read as green/red switches, sections fold, the command bar keeps its labels."""
import asyncio

from isycode.contracts import CatalogSnapshot
from isycode.tui import GREEN, RED, TUIApp, switch_row
from isycode.user_defaults import UserDefaultsStore


def _colours(text):
    return {str(span.style) for span in text.spans}


def test_switch_rows_are_green_when_on_and_red_when_off():
    assert any(GREEN in style for style in _colours(switch_row(True, "pyright")))
    assert any(RED in style for style in _colours(switch_row(False, "pyright", "unsupported")))
    assert "unsupported" in switch_row(False, "pyright", "unsupported").plain


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
