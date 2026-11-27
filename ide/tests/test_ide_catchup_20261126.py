"""Regression tests for ISyCode IDE catch-up (Fases 1-3, C-01..C-20 + ISyCo/ISyMCP)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.runtime.base import SandboxRuntime, ToolCall
from core.runtime.linux import LinuxCommandRuntime
from ui.app import AppController
from ui.main import resolve_initial_workspace
from ui.main_window import MainWindow


def test_glob_inside_workspace_ok_and_outside_actionable(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text("x = 1\n", encoding="utf-8")
    rt = SandboxRuntime(tmp_path)

    ok = asyncio.run(rt.execute(ToolCall("glob", {"pattern": "src/*.py"}, "g1")))
    assert ok.success
    assert "src/demo.py" in ok.stdout

    outside = asyncio.run(rt.execute(ToolCall("glob", {"pattern": "../outside/*.py"}, "g2")))
    assert not outside.success
    assert outside.error_code == "PATH_OUTSIDE_WORKSPACE"
    assert "Vincula esa carpeta o acota el patrón" in outside.stderr


def test_linux_runtime_normalizes_empty_cwd(tmp_path):
    rt = LinuxCommandRuntime(tmp_path)
    req = rt.prepare({"argv": ["python3", "-V"], "cwd": ""})
    assert req.identity.cwd == "."


def test_resolve_initial_workspace_prefers_saved_project(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    proj = tmp_path / "my_project"
    proj.mkdir()
    monkeypatch.setattr("core.ide_state.state_home", lambda: state_dir)
    monkeypatch.setattr("core.ui_preferences.state_home", lambda: state_dir)
    from core.ui_preferences import UiPreferences
    UiPreferences().save(last_workspace=str(proj))
    assert resolve_initial_workspace(None) == proj.resolve()


def test_all_technical_pages_are_visible_not_hidden(qtbot, tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setattr("core.ide_state.state_home", lambda: state_dir)
    monkeypatch.setattr("core.ui_preferences.state_home", lambda: state_dir)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    win = MainWindow(controller=AppController(tmp_path))
    qtbot.addWidget(win)
    win.show()

    # Regression for C-06..C-09: finish_pages() must unhide reparented page widgets.
    for title in ("Tool calls", "Tests", "Evidence", "Terminal"):
        win.panel_bar.show_title(title)
        panel = win.panel_bar._by_title[title]
        assert not panel.content().isHidden(), f"Panel {title} was hidden!"

    # C-07: Tests discovery
    assert "test_sample.py" in win.tests_panel.discovery_label.text()
    # C-08 + ISyCo/ISyMCP ecosystem tab
    assert win.tools_panel.eco_table.rowCount() >= 5
    # C-06: Live tool receipt updates Evidence
    win._on_tool_result({"id": "r1", "tool": "glob", "success": True, "stdout": "README.md", "stderr": "", "evidence": {}})
    assert win.evidence_panel.receipts_tree.topLevelItemCount() >= 1
    # C-10: Multi-file editor tabs
    assert win.editor_panel.open_file(tmp_path / "README.md")
    assert win.editor_panel.open_file(tmp_path / "tests" / "test_sample.py")
    assert win.editor_panel.file_tabs.count() == 2
    # C-03 & C-05: Status explains LAYER_B/C and scans resident
    win.status_panel._scan_resident()
    assert win.controller.resident_status().get("components", 0) >= 1
    # C-13: Config panel displays keyring status
    assert "Keyring" in win.config_panel.storage_label.text() or "keyring" in win.config_panel.storage_label.text().lower()
    # C-19: Context meter reflects real prompt tokens
    win._total_tokens_estimated = 42
    win._update_context_meter(42)
    assert "42" in win.context_meter.text()
    # Stop terminal child process cleanly before teardown
    if win.terminal_panel._process is not None:
        win.terminal_panel._process.kill()
        win.terminal_panel._process.waitForFinished(1000)


def test_isymcp_hub_replaces_cambios_and_obsidian_isymem_graph_loads(qtbot, tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setattr("core.ide_state.state_home", lambda: state_dir)
    monkeypatch.setattr("core.ui_preferences.state_home", lambda: state_dir)

    # Create a tiny fixture isymem bank inside tmp_path
    mem = tmp_path / "docs" / "agent" / "memory"
    mem.mkdir(parents=True)
    (mem / "hub-demo.md").write_text("---\nname: Demo Hub\ntype: project\nproject: demo\n---\nLinks [[note-a]]\n", encoding="utf-8")
    (mem / "note-a.md").write_text("---\nname: Note A\ntype: feedback\nproject: demo\n---\nBack to [[hub-demo]]\n", encoding="utf-8")

    win = MainWindow(controller=AppController(tmp_path))
    qtbot.addWidget(win)
    win.show()

    # Left nav has ISyMCP Hub instead of redundant Cambios
    assert "ISyMCP" in win.panel_bar.nav_buttons
    assert "Cambios" not in win.panel_bar.nav_buttons
    assert win.isymcp_panel.tabs.count() == 3
    assert win.isymcp_panel.conn_table.rowCount() >= 6

    # Obsidian isymem graph loaded nodes & edges
    assert len(win.resident_panel._isymem_graph["nodes"]) == 2
    assert len(win.resident_panel._isymem_graph["edges"]) == 1

    # Error recovery card exposes inline model switcher
    win._last_prompt = "hola"
    win._discovered_models["nvidia"] = ["model-a", "model-b"]
    win._on_agent_error("PROVIDER_HTTP_429 · rate limited")
    assert win.config_panel.health_pill is not None
    assert win.config_panel.model_browser is not None

    # UiPreferences persists github_auto_verify
    from core.ui_preferences import UiPreferences
    saved = UiPreferences().save(github_auto_verify=True)
    assert saved["github_auto_verify"] is True
    assert UiPreferences().load()["github_auto_verify"] is True

