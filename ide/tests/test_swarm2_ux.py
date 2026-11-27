"""Swarm-2 UX & P0/P1 regression tests covering editor, chat, isymcp, resident, and shell."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QMessageBox

from ui.app import AppController
from ui.panels.chat import ApprovalCard, ChatPanel
from ui.panels.editor import EditorPanel
from ui.panels.isymcp import ISyMCPControlPanel
from ui.panels.resident import load_isymem_graph
from ui.shell import DesktopShell


@pytest.fixture(autouse=True)
def _flush_qt_deferred_deletes():
    yield
    app = QCoreApplication.instance()
    if app is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return AppController(tmp_path)


# ---------------------------------------------------------------------------
# 1. EditorPanel: shortcuts, find/replace, save_button state, dirty guard, watcher
# ---------------------------------------------------------------------------


def test_editor_save_button_clean_dirty_and_shortcuts(qtbot, controller, tmp_path):
    f1 = tmp_path / "alpha.py"
    f2 = tmp_path / "beta.py"
    f1.write_text("hello world\nhello again\n", encoding="utf-8")
    f2.write_text("second file\n", encoding="utf-8")

    panel = EditorPanel(controller)
    qtbot.addWidget(panel)
    panel.show()

    # Initially disabled
    assert not panel.save_button.isEnabled()

    # Freshly opened file matches snapshot -> save_button stays disabled
    assert panel.open_file(f1)
    assert not panel.dirty()
    assert not panel.save_button.isEnabled()

    # Editing enables save_button; reverting to snapshot disables it again
    panel.editor.setPlainText("hello world\nhello again\n# edit\n")
    assert panel.dirty()
    assert panel.save_button.isEnabled()

    panel.editor.setPlainText("hello world\nhello again\n")
    assert not panel.dirty()
    assert not panel.save_button.isEnabled()

    # Shortcuts are scoped to EditorPanel
    for sc in (panel._shortcut_save, panel._shortcut_close, panel._shortcut_find, panel._shortcut_next_tab):
        assert sc.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut

    # Open second file & cycle tabs via Ctrl+Tab helper
    assert panel.open_file(f2)
    assert panel.file_tabs.count() == 2
    assert panel.current_path == f2
    panel.next_tab()
    assert panel.current_path == f1
    assert not panel.save_button.isEnabled()

    # Inline Find/Replace bar toggle, find next/prev, replace
    assert not panel.find_bar.isVisible()
    panel.toggle_find_bar()
    assert panel.find_bar.isVisible()
    panel.find_input.setText("hello")
    panel.replace_input.setText("hola")
    assert panel.find_next()
    assert panel.editor.textCursor().selectedText() == "hello"
    assert panel.replace_current()
    assert panel.editor.toPlainText().startswith("hola world\n")
    assert panel.dirty()
    assert panel.save_button.isEnabled()

    # Replace remaining & verify find_prev wraps cleanly
    assert panel.replace_all() == 1
    assert panel.editor.toPlainText() == "hola world\nhola again\n"
    panel.find_input.setText("hola")
    assert panel.find_prev()

    # Save disables save_button again
    assert panel.save()
    assert not panel.dirty()
    assert not panel.save_button.isEnabled()
    assert f1.read_text(encoding="utf-8") == "hola world\nhola again\n"

    # Toggle Find bar off
    panel.toggle_find_bar()
    assert not panel.find_bar.isVisible()


def test_editor_unsaved_guard_close_tab_and_reset_workspace(qtbot, controller, tmp_path, monkeypatch):
    f1 = tmp_path / "dirty.py"
    f1.write_text("x = 1\n", encoding="utf-8")

    panel = EditorPanel(controller)
    qtbot.addWidget(panel)
    assert panel.open_file(f1)
    panel.editor.setPlainText("x = 2\n")
    assert panel.dirty()

    # User cancels closing dirty tab -> tab remains open with draft intact
    prompts = []

    def _deny(*args, **kwargs):
        prompts.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", _deny)
    assert panel._close_tab(0) is False
    assert panel.file_tabs.count() == 1
    assert panel.editor.toPlainText() == "x = 2\n"
    assert len(prompts) == 1

    # Interactive reset_workspace also asks and respects cancel
    assert panel.reset_workspace() is False
    assert panel.file_tabs.count() == 1
    assert len(prompts) == 2

    # Programmatic force=True bypasses dialog and resets cleanly
    assert panel.reset_workspace(force=True) is True
    assert panel.file_tabs.count() == 0
    assert panel.current_path is None
    assert len(prompts) == 2

    # Dirty tab close with confirmation (Yes) succeeds
    assert panel.open_file(f1)
    panel.editor.setPlainText("x = 3\n")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    assert panel._close_tab(0) is True
    assert panel.file_tabs.count() == 0


def test_editor_external_change_watcher_banner_reload_and_ignore(qtbot, controller, tmp_path):
    target = tmp_path / "watched.py"
    target.write_text("v1 = 1\n", encoding="utf-8")

    panel = EditorPanel(controller)
    qtbot.addWidget(panel)
    panel.show()

    assert panel.open_file(target)
    assert not panel.reload_banner.isVisible()

    # Own save must NOT trigger external reload banner
    panel.editor.setPlainText("v2 = 2\n")
    assert panel.save()
    qtbot.wait(30)
    assert not panel.reload_banner.isVisible()

    # External disk write triggers inline reload banner
    target.write_text("v3_external = 3\n", encoding="utf-8")
    panel._on_external_file_changed(str(target))
    assert panel.reload_banner.isVisible()
    assert "El archivo cambió en disco" in panel.reload_label.text()

    # Clicking Ignorar hides banner and suppresses duplicate alerts for same disk state
    panel.ignore_reload_button.click()
    assert not panel.reload_banner.isVisible()
    panel._on_external_file_changed(str(target))
    assert not panel.reload_banner.isVisible()

    # Another external change re-shows banner, and Recargar updates buffer
    target.write_text("v4_reloaded = 4\n", encoding="utf-8")
    panel._on_external_file_changed(str(target))
    assert panel.reload_banner.isVisible()
    panel.reload_button.click()
    assert not panel.reload_banner.isVisible()
    assert panel.editor.toPlainText() == "v4_reloaded = 4\n"
    assert not panel.dirty()
    assert not panel.save_button.isEnabled()


# ---------------------------------------------------------------------------
# 2. ChatPanel: persistent composer notice bar & ApprovalCard shortcut isolation
# ---------------------------------------------------------------------------


def test_chat_composer_notices_set_update_action_and_clear(qtbot):
    chat = ChatPanel()
    qtbot.addWidget(chat)
    chat.show()

    assert not chat.composer_notices_container.isVisible()

    clicked = []
    notice = chat.set_composer_notice(
        "provider",
        "No hay provider configurado.",
        action_label="Configurar",
        callback=lambda: clicked.append("setup"),
    )
    assert chat.composer_notices_container.isVisible()
    assert notice.notice_label.text() == "No hay provider configurado."
    assert notice.action_button is not None
    notice.action_button.click()
    assert clicked == ["setup"]

    # Updating same key replaces without duplicating
    notice2 = chat.set_composer_notice("provider", "Provider actualizado.")
    assert len(chat._composer_notices) == 1
    assert notice2.notice_label.text() == "Provider actualizado."

    # Notice bar sits above the prompt composer input
    qtbot.wait(20)
    assert chat.composer_notices_container.geometry().bottom() <= chat.input.geometry().top() + 8

    # Clearing removes and hides container when empty
    assert chat.clear_composer_notice("provider") is True
    assert chat.clear_composer_notice("provider") is False
    assert not chat.composer_notices_container.isVisible()


def test_approval_card_does_not_steal_keys_or_focus_from_composer(qtbot):
    chat = ChatPanel()
    qtbot.addWidget(chat)
    chat.show()

    # User is actively typing in PromptComposer
    chat.input.setFocus()
    chat.input.setPlainText("draft ")
    qtbot.wait(20)
    assert chat.input.hasFocus()

    card = chat.add_approval_card("appr-leak", "write", {"path": "a.py"}, "+line")
    decisions = []
    card.decision_made.connect(decisions.append)

    # Focus was NOT stolen from composer
    assert chat.input.hasFocus()
    assert not card.reject_button.hasFocus()

    # Typing Y, N, Esc in PromptComposer must NOT trigger ApprovalCard decisions
    qtbot.keyClick(chat.input, Qt.Key.Key_Y)
    qtbot.keyClick(chat.input, Qt.Key.Key_N)
    qtbot.keyClick(chat.input, Qt.Key.Key_Escape)
    assert decisions == []
    assert not card._decided
    assert "yn" in chat.input.toPlainText().lower()

    # Focusing the card itself (e.g. reject_button) still allows Y/N/Esc keyboard decision
    card.reject_button.setFocus()
    qtbot.wait(10)
    qtbot.keyClick(card.reject_button, Qt.Key.Key_Y)
    assert decisions == [True]
    assert card._decided is True


# ---------------------------------------------------------------------------
# 3. ISyMCPControlPanel: corrupted mcp.json warning + .bak backup before write
# ---------------------------------------------------------------------------


def test_isymcp_corrupted_json_warns_and_creates_bak_before_write(qtbot, controller, tmp_path, monkeypatch):
    bad_cfg = tmp_path / ".config" / "isycode" / "mcp.json"
    bad_cfg.parent.mkdir(parents=True, exist_ok=True)
    raw_corrupt = "{broken json: [1, 2,"
    bad_cfg.write_text(raw_corrupt, encoding="utf-8")

    monkeypatch.setattr("ui.panels.isymcp._mcp_config_path", lambda: bad_cfg)
    monkeypatch.setattr(ISyMCPControlPanel, "_port_open", staticmethod(lambda _port: False))

    panel = ISyMCPControlPanel(controller)
    qtbot.addWidget(panel)
    panel.show()

    # _load_mcp_json must NOT silently return {} or overwrite the file
    cfg, data = panel._load_mcp_json()
    assert cfg == bad_cfg
    assert data is None
    assert panel._mcp_parse_error is not None
    assert panel.mcp_warning_banner.isVisible()
    assert bad_cfg.read_text(encoding="utf-8") == raw_corrupt

    # Writing new config creates timestamped .bak preserving original corrupted bytes
    backup = panel._write_mcp_json(bad_cfg, {"mcpServers": {"demo": {"url": "http://127.0.0.1:8798/mcp"}}})
    assert backup is not None
    assert backup.is_file()
    assert backup.name.startswith("mcp.json.") and backup.name.endswith(".bak")
    assert backup.read_text(encoding="utf-8") == raw_corrupt

    # New mcp.json is valid JSON and banner clears on refresh
    parsed = json.loads(bad_cfg.read_text(encoding="utf-8"))
    assert "demo" in parsed["mcpServers"]
    panel._refresh_mcp_servers()
    assert panel._mcp_parse_error is None
    assert not panel.mcp_warning_banner.isVisible()
    assert panel.mcp_table.rowCount() == 1


# ---------------------------------------------------------------------------
# 4. ResidentPanel: load_isymem_graph stays fast (<150ms) for 100+ nodes
# ---------------------------------------------------------------------------


def test_load_isymem_graph_large_graph_performance(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "MEMORY.md").write_text("# Index\n[[hub-alpha]] [[hub-beta]]\n", encoding="utf-8")
    (mem_dir / "hub-alpha.md").write_text("---\nname: Alpha\nproject: alpha\n---\n", encoding="utf-8")
    (mem_dir / "hub-beta.md").write_text("---\nname: Beta\nproject: beta\n---\n", encoding="utf-8")

    for i in range(120):
        proj = "alpha" if i % 2 == 0 else "beta"
        nxt = f"node-{(i + 1) % 120}"
        (mem_dir / f"node-{i}.md").write_text(
            f"---\nname: Node {i}\ntype: project\nproject: {proj}\n---\nSee [[{nxt}]]\n",
            encoding="utf-8",
        )

    t0 = time.perf_counter()
    graph = load_isymem_graph(mem_dir)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert len(graph["nodes"]) == 123
    assert len(graph["edges"]) >= 120
    assert all(isinstance(nd["x"], float) and isinstance(nd["y"], float) for nd in graph["nodes"])
    assert elapsed_ms < 150.0, f"load_isymem_graph took {elapsed_ms:.1f}ms (expected < 150ms)"


# ---------------------------------------------------------------------------
# 5. DesktopShell: set_nav_badge counters without breaking nav_buttons
# ---------------------------------------------------------------------------


def test_desktop_shell_set_nav_badge(qtbot):
    shell = DesktopShell()
    qtbot.addWidget(shell)
    shell.resize(1300, 800)
    shell.show()

    assert shell.nav_buttons["Evidence"].text() == "Evidencia"
    shell.set_nav_badge("Evidence", 3)
    assert shell.nav_buttons["Evidence"].text() == "Evidencia (3)"

    # Clearing badge (0 or negative) restores original label
    shell.set_nav_badge("Evidence", 0)
    assert shell.nav_buttons["Evidence"].text() == "Evidencia"

    # Preserved across compact/expanded resize transitions
    shell.set_nav_badge("Evidence", 7)
    shell.resize(900, 700)
    qtbot.wait(20)
    assert shell.nav_buttons["Evidence"].text() == "7"
    shell.resize(1300, 800)
    qtbot.wait(20)
    assert shell.nav_buttons["Evidence"].text() == "Evidencia (7)"

    # Unknown title is a safe no-op
    shell.set_nav_badge("NonExistent", 5)
