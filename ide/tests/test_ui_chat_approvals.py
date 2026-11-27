"""Unit tests for ChatPanel, PromptComposer, ApprovalCard and AgentWorker approval flow."""

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import tempfile
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ui.app import AppController
from ui.main_window import MainWindow
from ui.panels.chat import ChatPanel, PromptComposer, ApprovalCard


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_prompt_composer_shortcuts_and_expansion(qapp):
    composer = PromptComposer()
    assert composer.height() == 38

    # Multi-line expansion
    composer.setPlainText("Line 1\nLine 2\nLine 3\nLine 4\nLine 5")
    assert composer.height() > 38

    # History navigation
    composer._record_history("prompt 1")
    composer._record_history("prompt 2")
    composer.setPlainText("")

    # Navigate up
    nav_up = composer._navigate_history(-1)
    assert nav_up is True
    assert composer.toPlainText() == "prompt 2"

    nav_up2 = composer._navigate_history(-1)
    assert nav_up2 is True
    assert composer.toPlainText() == "prompt 1"


def test_approval_card_decisions(qapp):
    card = ApprovalCard("appr-1", "write", {"path": "test.py", "content": "hello"}, "Write hello to test.py")
    results = []
    card.decision_made.connect(lambda v: results.append(v))

    # Reject
    card.reject_button.click()
    assert results == [False]
    assert card._decided is True
    assert "RECHAZADO" in card.status_badge.text()

    # Second click should be ignored
    card.approve_button.click()
    assert results == [False]


def test_approval_card_approve(qapp):
    card = ApprovalCard("appr-2", "edit", {"path": "test.py"}, "Edit test.py")
    results = []
    card.decision_made.connect(lambda v: results.append(v))

    card.approve_button.click()
    assert results == [True]
    assert card._decided is True
    assert "APROBADO" in card.status_badge.text()


def test_main_window_wiring_with_approval(qapp):
    with tempfile.TemporaryDirectory() as tmp:
        ctrl = AppController(tmp)
        win = MainWindow(controller=ctrl)
        
        # Test adding approval card to chat
        card = win.chat.add_approval_card("aid-123", "python", {"code": "print(1)"}, "Run print(1)")
        assert win.chat.active_approval_card() is card
        assert card.approval_id == "aid-123"

        # Simulate operator rejection
        card.reject_button.click()
        assert card._decided is True
        win.close()


def test_streaming_markdown_and_copy(qapp):
    chat = ChatPanel()
    chat.start_assistant_stream()
    chat.append_chunk("# Hello\n\nHere is `code`:\n```python\nx = 1\n```")
    assert chat._streaming_bubble is not None
    html_content = chat._streaming_bubble.content_browser.toHtml()
    assert "Hello" in html_content
    assert "code" in html_content
    # Test copy
    chat._streaming_bubble._copy_response()
    assert chat._streaming_bubble.copy_btn.text() == "Copiado ✓"
    chat.end_assistant_stream()
    assert chat._streaming_bubble is None


def test_workspace_git_and_context_meter(qapp):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "hello.py").write_text("print('hello')", encoding="utf-8")
        ctrl = AppController(tmp)
        win = MainWindow(controller=ctrl)

        # Context meter update
        win._update_context_meter(500)
        assert "500" in win.context_meter.text()

        # New session resets tokens
        win._new_session()
        assert win._total_tokens_estimated == 0
        assert "0" in win.context_meter.text()

        # Workspace git status call
        win.workspace.refresh_git_status()
        assert win.workspace.git_label is not None
        win.close()


def test_approval_card_auto_hides_on_approve_and_compacts_on_reject(qapp):
    chat = ChatPanel()
    approved_card = chat.add_approval_card("appr-hide", "run_command", {"command": "echo hi"}, "argv: ['echo', 'hi']")
    assert approved_card.isHidden() is False
    approved_card.approve_button.click()
    assert approved_card._decided is True
    assert approved_card.isHidden() is True

    rejected_card = chat.add_approval_card("appr-rej", "run_command", {"command": "rm -rf /"}, "argv: ['rm', '-rf', '/']")
    rejected_card.reject_button.click()
    assert rejected_card._decided is True
    assert rejected_card.isHidden() is False
    assert rejected_card._title_label.text() == "Propuesta rechazada"
    assert hasattr(rejected_card, "_toggle_details_btn")
    assert rejected_card.detail_view.isHidden() is True


def test_multi_tool_steps_auto_collapse_on_reply_and_toggle(qapp):
    chat = ChatPanel()
    chat.start_assistant_stream()
    tool_bubble = chat._streaming_bubble
    c1 = chat.add_tool_call("read", {"path": "a.py"})
    c1.set_result(True, stdout="ok")
    c2 = chat.add_tool_call("run_command", {"command": "pytest"})
    c2.set_result(False, stderr="failed", returncode=1)

    # Before final text arrives, tools are expanded
    assert tool_bubble.tools_box.isHidden() is False

    # Streaming final text spawns a new bubble below and collapses the previous tool stack
    chat.append_chunk("Resumen final tras revisar los archivos.")
    assert chat._streaming_bubble is not tool_bubble
    assert tool_bubble.tools_box.isHidden() is True
    assert tool_bubble.tools_toggle.isHidden() is False
    assert "2 pasos de herramientas" in tool_bubble.tools_toggle.text()
    assert "1 ok" in tool_bubble.tools_toggle.text()
    assert "1 falló" in tool_bubble.tools_toggle.text()

    # Clicking the toggle expands the tool cards again
    tool_bubble.tools_toggle.click()
    assert tool_bubble.tools_box.isHidden() is False
    chat.end_assistant_stream()
