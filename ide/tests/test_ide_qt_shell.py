"""Native layout/state checks with private test configuration and no network."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ui.app import AppController
from ui.main_window import MainWindow
from ui.panels.chat import ApprovalCard


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_IDE_HOME", str(tmp_path / "private-state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("print('sample')\n")
    widget = MainWindow(AppController(root))
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.close()


def test_unconfigured_provider_is_visible_and_actionable(window):
    assert window.provider_combo.count() == 0
    assert window.model_combo.count() == 0
    assert window.chat.empty_state.configure_button.isVisible()
    window.chat.empty_state.configure_button.click()
    assert window.panel_bar.pages.currentWidget() is window.config_panel


def test_switching_views_keeps_same_chat_session_and_draft(window):
    window._session_id = "same-session"
    window.chat.input.setPlainText("unfinished request")
    chat = window.chat
    editor = window.editor_panel
    window.panel_bar.set_view("code")
    assert window.panel_bar.work_split.widget(0) is window.panel_bar.inspector
    window.panel_bar.set_view("conversation")
    assert window.panel_bar.work_split.widget(0) is chat
    assert window.chat is chat and window.editor_panel is editor
    assert window._session_id == "same-session"
    assert chat.input.toPlainText() == "unfinished request"


def test_conversation_rail_and_navigation_follow_view_switch(window):
    assert window.conversations_panel.isVisible()
    window.panel_bar.show_title("Config")
    window.panel_bar.set_view("conversation")
    assert window.panel_bar.nav_buttons["Conversaciones"].isChecked()


def test_navigation_destinations_have_distinct_layouts_and_keep_draft(window, qtbot):
    shell = window.panel_bar
    window.chat.input.setPlainText("same unfinished request")
    shell.nav_buttons["Editor"].click()
    qtbot.wait(30)
    assert shell.view == "code" and shell.work_split.widget(0) is shell.inspector
    assert not window.conversations_panel.isVisible()
    shell.nav_buttons["Conversaciones"].click()
    qtbot.wait(30)
    assert shell.view == "conversation" and shell.work_split.widget(0) is window.chat
    assert window.conversations_panel.isVisible()
    assert not shell.inspector.isVisible()  # no empty editor taking half the chat
    assert window.chat.input.toPlainText() == "same unfinished request"
    window._open_file(str(window.controller.working_dir / "app.py"))
    shell.nav_buttons["Conversaciones"].click()
    assert shell.inspector.isVisible()  # an opened file remains available


def test_floating_panel_returns_to_its_page(window):
    dialog = window.open_panel_window("GitHub")
    assert window.github_panel.parent() is dialog
    dialog.close()
    window.panel_bar.show_title("GitHub")
    assert window.panel_bar.pages.currentWidget() is window.github_panel


def test_command_always_choice_does_not_exist_on_file_card(qtbot):
    command = ApprovalCard("id", "run_command", {"approval_kind": "command", "argv": ["true"]}, "argv: true")
    qtbot.addWidget(command)
    with qtbot.waitSignal(command.decision_made) as signal:
        command.always_button.click()
    assert signal.args == ["always"]
    assert not command.always_button.isEnabled()
    file_card = ApprovalCard("id2", "write", {"path": "app.py"}, "diff")
    qtbot.addWidget(file_card)
    assert file_card.always_button is None


def test_workspace_switch_keeps_unsaved_editor_draft(window, tmp_path):
    original = window.controller.working_dir
    window._open_file(str(original / "app.py"))
    window.editor_panel.editor.insertPlainText("unsaved")
    new = tmp_path / "other"
    new.mkdir()
    window._switch_workspace(str(new))
    assert window.controller.working_dir == original
    assert "unsaved" in window.editor_panel.editor.toPlainText()


def test_failed_github_refresh_invalidates_project_footer(window):
    window.github_panel._selected_folder = str(window.controller.working_dir)
    window.git_notice.setText("GitHub · 5 detrás · 0 delante")
    window.github_panel._failed("Session expired")
    assert "sin comprobar" in window.git_notice.text()


def test_scroll_return_does_not_overlay_messages(window, qtbot):
    window.resize(1366, 768)
    window.panel_bar.set_view("code")
    for index in range(12):
        window.chat.add_approval_card(str(index), "write", {"path": "app.py"}, "sample diff")
    qtbot.wait(50)
    window.chat.scroll.verticalScrollBar().setValue(0)
    qtbot.wait(50)
    button = window.chat.scroll_bottom_btn
    assert button.isVisible()
    assert button.geometry().top() > window.chat.stack.geometry().bottom()
    button.click()
    qtbot.wait(50)
    assert not button.isVisible()


def test_copy_feedback_cannot_outlive_destroyed_bubble(qtbot):
    import shiboken6
    from ui.panels.chat import StreamingAssistantBubble
    widget = StreamingAssistantBubble()
    widget.append_chunk("fixture response")
    widget._copy_response()
    shiboken6.delete(widget)
    qtbot.wait(1550)


def test_compact_chat_keeps_entire_wrapped_response_visible(window, qtbot):
    from PySide6.QtGui import QTextCursor
    window.chat.start_assistant_stream()
    window.chat.append_chunk("## Revisión\n" + ("Una respuesta con varias palabras para comprobar la altura. " * 6))
    browser = window.chat._streaming_bubble.content_browser
    window.resize(1366, 768)
    window.panel_bar.set_view("code")
    qtbot.wait(80)
    cursor = QTextCursor(browser.document())
    cursor.movePosition(QTextCursor.MoveOperation.End)
    assert browser.cursorRect(cursor).bottom() <= browser.viewport().height()


def test_compact_approvals_do_not_clip_decision_buttons(window, qtbot):
    from PySide6.QtCore import QPoint
    card = window.chat.add_approval_card("fixture", "write", {"path": "app.py"}, "+new line")
    window.resize(1366, 768)
    window.panel_bar.set_view("code")
    qtbot.wait(80)
    viewport = window.chat.scroll.viewport()
    assert window.chat.messages_container.width() <= viewport.width()
    for button in (card.approve_button, card.reject_button, card.review_button):
        left = button.mapTo(viewport, QPoint(0, 0)).x()
        assert left >= 0 and left + button.width() <= viewport.width()
