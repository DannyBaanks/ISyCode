"""MVP-2 panel tests (Qt offscreen, no network)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ui.app import AppController
from ui.diff import render_diff, has_changes


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return AppController(tmp_path)


def test_diff_renderer():
    old_text = "a\nb\nc\n"
    new_text = "a\nB\nc\nd\n"
    assert has_changes(old_text, new_text)
    html = render_diff(old_text, new_text)
    assert "diff-add" in html and "diff-del" in html
    assert not has_changes("same\n", "same\n")
    assert "no changes" in render_diff("same\n", "same\n")


def test_workspace_panel_tree_and_search(qtbot, controller, tmp_path):
    from ui.panels.workspace import WorkspacePanel
    (tmp_path / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "beta.md").write_text("# t\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("ignored\n", encoding="utf-8")

    panel = WorkspacePanel()
    qtbot.addWidget(panel)
    panel.set_root(tmp_path)
    assert panel.tree.model() is not None

    panel.search.setText("alpha")
    assert panel.results.isVisibleTo(panel) or not panel.results.isHidden()
    assert panel.results.count() == 1
    assert ".git" not in panel.results.item(0).text()

    panel.search.clear()
    assert panel.tree.isVisibleTo(panel) or not panel.tree.isHidden()


def test_editor_boundary_save(qtbot, controller, tmp_path):
    from ui.panels.editor import EditorPanel
    target = tmp_path / "notes.txt"
    target.write_text("original\n", encoding="utf-8")

    panel = EditorPanel(controller)
    qtbot.addWidget(panel)
    assert panel.open_file(str(target))
    assert panel.editor.toPlainText() == "original\n"
    assert not panel.dirty()

    panel.editor.setPlainText("edited\n")
    assert panel.dirty()
    assert panel.save()
    assert target.read_text(encoding="utf-8") == "edited\n"
    assert not panel.dirty()


def test_editor_rejects_outside_workspace(qtbot, controller, tmp_path):
    from ui.panels.editor import EditorPanel
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    panel = EditorPanel(controller)
    qtbot.addWidget(panel)
    assert not panel.open_file(str(outside))
    assert panel.current_path is None


def test_policy_panel_table(qtbot, controller):
    from ui.panels.policy import PolicyPanel
    panel = PolicyPanel(controller)
    qtbot.addWidget(panel)
    assert panel.table.rowCount() == len(controller.policy_rules())
    assert panel.table.item(0, 0).text() == "network"


def test_resident_panel_scan_and_query(qtbot, controller, tmp_path):
    from ui.panels.resident import ResidentPanel
    (tmp_path / "demo.py").write_text("print(1)\n", encoding="utf-8")
    panel = ResidentPanel(controller)
    qtbot.addWidget(panel)
    panel.run_scan()
    text = panel.view.toPlainText()
    assert '"status": "ok"' in text
    panel.query_input.setText("runtime boundary")
    panel.run_query()
    assert "guidance" in panel.view.toPlainText()


def test_config_panel_add_and_remove(qtbot, controller, monkeypatch):
    from ui.panels.config import ConfigPanel
    panel = ConfigPanel(controller)
    qtbot.addWidget(panel)
    changed = []
    panel.providers_changed.connect(lambda: changed.append(True))

    panel.name_input.setText("myprov")
    panel.type_combo.setCurrentText("ollama")
    panel.model_input.setCurrentText("llama3.1")
    panel.add_provider()
    assert changed == [True]
    assert "myprov" in controller.providers()

    panel.remove_button  # exists
    selected = next(panel.profiles.item(i) for i in range(panel.profiles.count()) if panel.profiles.item(i).data(__import__('PySide6.QtCore', fromlist=['Qt']).Qt.ItemDataRole.UserRole) == "myprov")
    panel.profiles.setCurrentItem(selected)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    panel.remove_provider()
    assert "myprov" not in controller.providers()


def test_terminal_panel_constructs(qtbot, controller):
    from PySide6.QtWidgets import QLabel
    from ui.panels.terminal import TerminalPanel
    panel = TerminalPanel(controller)
    qtbot.addWidget(panel)
    banner = panel.findChild(QLabel)
    assert banner is not None and "HOST SHELL" in banner.text()


def test_evidence_panel_constructs(qtbot, controller):
    from ui.panels.evidence import EvidencePanel
    panel = EvidencePanel(controller)
    qtbot.addWidget(panel)
    assert panel.tree is not None


def test_tests_panel_constructs(qtbot, controller):
    from ui.panels.tests import TestsPanel
    panel = TestsPanel(controller)
    qtbot.addWidget(panel)
    assert not panel.output.toPlainText()


def test_main_window_full_layout(qtbot, controller):
    from ui.main_window import MainWindow
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    # Check collapsible panels exist
    panel_titles = [p.title() for p in window.panel_bar.panels()]
    for expected in ["Editor", "Tool calls", "Diff", "Tests", "Evidence",
                     "Policy", "Resident", "Config", "Terminal", "Status"]:
        assert expected in panel_titles
    assert window.workspace.tree.model() is not None
    window.close()


def test_main_window_open_file_and_diff(qtbot, controller, tmp_path):
    from ui.main_window import MainWindow
    target = tmp_path / "code.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window._open_file(str(target))
    # Editor panel should be expanded
    assert window.editor_collapsible._expanded
    assert window.editor_panel.editor.toPlainText() == "def f():\n    return 1\n"
    window.editor_panel.editor.setPlainText("def f():\n    return 2\n")
    assert window.diff_browser.toHtml()
    window.close()