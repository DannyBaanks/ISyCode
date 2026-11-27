"""Qt smoke tests for the ISyCode window (offscreen platform)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ui.app import AppController
from ui.main_window import MainWindow
from ui.panels.chat import ChatPanel


@pytest.fixture
def controller(tmp_path):
    return AppController(tmp_path)


def test_main_window_constructs(qtbot, controller):
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    assert window.windowTitle().startswith("ISyCode")
    assert window.provider_combo.count() == 0
    assert window.model_combo.count() == 0
    assert window.mode_button.text() == "MODE: PLAN"
    assert len(window.panel_bar.panels()) >= 1
    window.close()


def test_main_window_provider_selection_updates_models(qtbot, controller):
    controller.add_provider("local", "ollama", "fixture-model")
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.provider_combo.setCurrentText("local")
    assert "fixture-model" in [window.model_combo.itemText(i)
                        for i in range(window.model_combo.count())]
    window.close()


def test_chat_panel_rendering(qtbot):
    panel = ChatPanel()
    qtbot.addWidget(panel)
    panel.add_user_message("hola")
    panel.start_assistant_stream()
    panel.append_chunk("respuesta ")
    panel.append_chunk("parcial")
    card = panel.add_tool_call("glob", {"pattern": "**/*.py"})
    card.set_result(True, "2 files", "", {})
    card2 = panel.add_tool_call("write", {"path": "boom.txt"})
    card2.set_result(False, "", "boom", {})
    panel.end_assistant_stream()
    panel.add_system_message("session ended")
    # Verify methods execute without error
    assert panel.messages_layout.count() >= 3
    panel.clear_log()
    assert panel.messages_layout.count() == 1  # only stretch remains


def test_tools_panel_records_events(qtbot):
    from ui.panels.tools import ToolsPanel
    panel = ToolsPanel()
    qtbot.addWidget(panel)
    panel.on_tool_call({"id": "t1", "tool": "edit",
                        "arguments": {"path": "a.py", "old": "x", "new": "y"}})
    panel.on_tool_result({"id": "t1", "tool": "edit", "success": True,
                          "stdout": "Edited a.py", "stderr": "",
                          "error_code": "", "evidence": {"actor": "CODER"}})
    assert panel.tree.topLevelItemCount() == 1
    item = panel.tree.topLevelItem(0)
    assert item.text(0) in {"edit", "Editar archivo"}
    assert item.text(1) in {"OK", "completado", "✓ completada"}