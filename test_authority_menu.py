"""Settings → Authority must open in every setup, and no local name may shadow an import."""
import ast
import asyncio
from pathlib import Path

import pytest

from isycode.tui import TUIApp
from isycode.user_defaults import UserDefaultsStore

PACKAGE = Path(__file__).parent / "isycode"
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

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            if pyright_ready:
                app._lsp_inventory = [{"id": "pyright", "state": "sandbox_ready",
                                       "sandbox_executable": "/usr/bin/bwrap",
                                       "server_executable": "/opt/pyright.js",
                                       "node_executable": "/usr/bin/node"}]
            app._open_authority_menu()
            await pilot.pause()
            return [entry["label"] for entry in app._menu_entries]

    with capsys.disabled():
        labels = asyncio.run(scenario())
    assert "Turn on all coding tools…" in labels
    assert any(label.startswith("Run commands in a sandbox") for label in labels)
    assert ("Check Python files after edits" in labels) is pyright_ready
