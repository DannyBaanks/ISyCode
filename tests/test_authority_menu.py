"""Settings → Authority must open in every setup, and no local name may shadow an import."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from isycode.tui import PreviewOptionList, TUIApp
from isycode.user_defaults import UserDefaultsStore

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "isycode"
# Pre-existing, harmless: the function reads a listener flag named http and never uses http.client.
SHADOW_EXCEPTIONS = {("tailscale.py", "_parse_serve", "http")}


def test_no_function_shadows_a_module_import_it_also_reads():
    """A local assignment makes the name local for the whole function, so an earlier call
    to the imported function raises UnboundLocalError (the Settings → Authority crash)."""
    problems = []
    for path in sorted(PACKAGE.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        imported = {(alias.asname or alias.name).split(".")[0]
                    for node in module.body if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names}
        for node in ast.walk(module):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = [item for item in ast.walk(node) if isinstance(item, ast.Name)]
            stored = {item.id for item in names if isinstance(item.ctx, ast.Store)}
            stored |= {arg.arg for arg in node.args.args + node.args.kwonlyargs}
            loaded = {item.id for item in names if isinstance(item.ctx, ast.Load)}
            for name in stored & imported & loaded:
                if (path.name, node.name, name) not in SHADOW_EXCEPTIONS:
                    problems.append(f"{path.name}:{node.lineno} {node.name} shadows {name}")
    assert problems == []


@pytest.mark.parametrize("pyright_ready", [False, True])
def test_authority_menu_opens_with_every_integration_state(tmp_path, monkeypatch, capsys,
                                                           pyright_ready):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="security")
    monkeypatch.setattr("isycode.tui.sandbox_executable", lambda: "/usr/bin/bwrap")

    async def workspace_startup(self):
        # This test inspects the authority menu, not optional startup catalog or
        # Gateway requests. Keep its UI harness independent of background I/O.
        return None

    monkeypatch.setattr(TUIApp, "_startup_workspace", workspace_startup)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._lsp_inventory = ([{"id": "pyright", "state": "sandbox_ready",
                                    "sandbox_executable": "/usr/bin/bwrap",
                                    "server_executable": "/opt/pyright.js",
                                    "node_executable": "/usr/bin/node"}]
                                  if pyright_ready else [])
            app._open_authority_menu()
            await pilot.pause()
            return [entry["label"] for entry in app._menu_entries]

    with capsys.disabled():
        labels = asyncio.run(scenario())
    assert "Turn on all coding tools…" in labels
    assert any(label.startswith("Run commands in a sandbox") for label in labels)
    assert ("Check Python files after edits" in labels) is pyright_ready


def _app_env(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="security")


def test_menu_is_a_large_centered_card_that_explains_each_option(tmp_path, monkeypatch, capsys):
    _app_env(tmp_path, monkeypatch)

    async def workspace_startup(self):
        # The menu layout does not depend on startup catalogs or file enumeration.
        return None

    monkeypatch.setattr(TUIApp, "_startup_workspace", workspace_startup)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            app._open_authority_menu()
            await pilot.pause()
            card = app.query_one("#action-card")
            assert card.size.width >= 100 and card.size.height >= 30
            detail = app.query_one("#action-detail")
            labels = [entry["label"] for entry in app._menu_filtered]
            target = labels.index("Read and search workspace files")
            options = app.query_one("#action-list")
            options.highlighted = target
            await pilot.pause()
            assert "list, read, and find files" in str(getattr(detail, "renderable", None) or detail.content)
            return labels

    with capsys.disabled():
        labels = asyncio.run(scenario())
    # Without an open saved conversation, deletion is explained instead of a dead toggle.
    assert not any(label.startswith("Delete current conversation") for label in labels)


def test_option_list_click_previews_and_double_click_selects():
    options = PreviewOptionList()
    options.add_option("Safe option")
    selected = []
    options.action_select = lambda: selected.append(options.highlighted)

    async def scenario():
        await options._on_click(SimpleNamespace(
            style=SimpleNamespace(meta={"option": 0}), chain=1,
        ))
        assert options.highlighted == 0
        assert selected == []
        await options._on_click(SimpleNamespace(
            style=SimpleNamespace(meta={"option": 0}), chain=2,
        ))
        assert selected == [0]

    asyncio.run(scenario())
