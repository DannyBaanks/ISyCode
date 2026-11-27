"""Chat panel: empty state, message bubbles, tool/approval cards and the composer.

All colours come from ui/theme.py (global QSS + DOCUMENT_CSS); widgets here
only declare objectName / dynamic properties.

Features:
- PromptComposer: auto-expanding (1-8 lines), Enter sends, Shift/Alt/Ctrl+Enter
  or Ctrl+J insert a newline, Up/Down walk the prompt history, Esc stops.
- ApprovalCard: human-in-the-loop prompt with a coloured diff; default is reject.
- Markdown rendering with auto-height bubbles (no inner scrollbars).
- Smart auto-scroll: follows the stream only while you are at the bottom.
"""

from __future__ import annotations

import difflib
import html
import json
import time
from pathlib import Path

import markdown
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QTextCursor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..tool_presentation import present_tool


def _render_markdown(text: str) -> str:
    body = markdown.markdown(text, extensions=["fenced_code", "tables"], output_format="html5")
    return body


def render_diff_html(text: str) -> str:
    """Colour a unified diff (or plain text) for the approval card."""
    rows = []
    for line in text.splitlines():
        esc = html.escape(line) or "&nbsp;"
        if line.startswith("+") and not line.startswith("+++"):
            rows.append(f'<div style="background:{theme.DIFF_ADD_BG};color:{theme.DIFF_ADD_FG};">{esc}</div>')
        elif line.startswith("-") and not line.startswith("---"):
            rows.append(f'<div style="background:{theme.DIFF_DEL_BG};color:{theme.DIFF_DEL_FG};">{esc}</div>')
        elif line.startswith("@@"):
            rows.append(f'<div style="color:{theme.DIFF_HDR_FG};">{esc}</div>')
        else:
            rows.append(f'<div style="color:{theme.DIFF_CTX_FG};">{esc}</div>')
    return f'<div style="font-family:{theme.MONO};white-space:pre;">{"".join(rows)}</div>'


def unified_diff(old: str, new: str, path: str) -> str:
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="", n=3))


class AutoTextBrowser(QTextBrowser):
    """Read-only rich text that grows to fit its content (no inner scroll)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDefaultStyleSheet(theme.DOCUMENT_CSS)
        self.document().setDocumentMargin(2)
        self.document().contentsChanged.connect(self._fit)

    def setMarkdownHtml(self, body: str) -> None:
        self.setHtml(body)
        self._fit()

    def _fit(self) -> None:
        self.document().setTextWidth(max(50, self.viewport().width()))
        height = int(self.document().size().height()) + self.frameWidth() * 2 + 4
        if self.height() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()


class PromptComposer(QPlainTextEdit):
    """Auto-expanding multi-line composer with history and keyboard shortcuts."""

    submit_requested = Signal(str)
    escape_pressed = Signal()
    returnPressed = submit_requested  # backward-compatible alias

    MIN_H = 38
    MAX_H = 180

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("promptComposer")
        self._history: list[str] = []
        self._history_index = -1
        self._current_draft = ""
        self.setPlaceholderText("Pregunta o pide un cambio…   Enter envía · Shift+Enter nueva línea")
        self.setTabChangesFocus(True)
        self.textChanged.connect(self._adjust_height)
        self.setFixedHeight(self.MIN_H)

    def _adjust_height(self) -> None:
        lines = max(1, self.document().lineCount())
        line_h = self.fontMetrics().lineSpacing()
        target = max(self.MIN_H, min(self.MAX_H, int(lines * line_h + 20)))
        if self.height() != target:
            self.setFixedHeight(target)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()
        newline_mods = (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.ControlModifier)

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & newline_mods:
                self.insertPlainText("\n")
                event.accept()
                return
            text = self.toPlainText().strip()
            if text:
                self._record_history(text)
                self.submit_requested.emit(text)
            event.accept()
            return
        if key == Qt.Key.Key_J and mods & Qt.KeyboardModifier.ControlModifier:
            self.insertPlainText("\n")
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            event.accept()
            return

        cursor = self.textCursor()
        if key == Qt.Key.Key_Up and (cursor.blockNumber() == 0 or not self.toPlainText()):
            if self._navigate_history(-1):
                event.accept()
                return
        elif key == Qt.Key.Key_Down and (
                cursor.blockNumber() == self.document().blockCount() - 1 or not self.toPlainText()):
            if self._navigate_history(1):
                event.accept()
                return
        super().keyPressEvent(event)

    def _record_history(self, prompt: str) -> None:
        if not self._history or self._history[-1] != prompt:
            self._history.append(prompt)
        self._history_index = -1
        self._current_draft = ""

    def _navigate_history(self, delta: int) -> bool:
        if not self._history:
            return False
        if self._history_index == -1:
            if delta > 0:
                return False
            self._current_draft = self.toPlainText()
            self._history_index = len(self._history) - 1
        else:
            new_idx = self._history_index + delta
            if new_idx >= len(self._history):
                self._history_index = -1
                self.setPlainText(self._current_draft)
                self.moveCursor(QTextCursor.MoveOperation.End)
                return True
            if new_idx < 0:
                return False
            self._history_index = new_idx
        self.setPlainText(self._history[self._history_index])
        self.moveCursor(QTextCursor.MoveOperation.End)
        return True

    def text(self) -> str:
        return self.toPlainText()


class ApprovalCard(QFrame):
    """Card shown when an agent action needs operator permission."""

    decision_made = Signal(object)

    def __init__(self, approval_id: str, tool_name: str, arguments: dict, diff: str, parent=None):
        super().__init__(parent)
        self.setObjectName("approvalCard")
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.diff = diff
        self._decided = False
        self._compact_mode = False
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        command = self.arguments.get("approval_kind") == "command"

        header = QHBoxLayout()
        self._header_row = header
        title = QLabel("Comando pendiente de aprobación" if command else "Cambios listos para revisar")
        title.setObjectName("approvalTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        self._title_label = title
        header.addWidget(title, 3)
        header.addStretch(1)
        self.status_badge = QLabel("ESPERANDO · tu aprobación")
        self.status_badge.setToolTip("Y aprueba · N/Esc rechaza")
        self.status_badge.setObjectName("approvalBadge")
        self.status_badge.setWordWrap(True)
        header.addWidget(self.status_badge, 2)
        layout.addLayout(header)

        paths = self.arguments.get("paths", [])
        path_label = QLabel("Comando aislado · " + str(self.arguments.get("cwd", ".")) if command else
                            str(self.arguments.get("path") or "\n".join(paths)))
        path_label.setTextFormat(Qt.TextFormat.PlainText)
        path_label.setWordWrap(True)
        self._path_label = path_label
        layout.addWidget(path_label)
        base = self.arguments.get("executable_sha256") if command else self.arguments.get("before_sha256")
        base_label = QLineEdit(f"SHA-256 {'ejecutable' if command else 'base'}: {base or ('varias bases en el diff' if paths else 'archivo nuevo')}")
        base_label.setReadOnly(True)
        base_label.hide()
        details = QPushButton("Identidad y base")
        self._base_details = details
        details.setProperty("variant", "ghost")
        details.setToolTip("Inspeccionar el hash de la base o del ejecutable antes de aprobar")
        details.clicked.connect(lambda: base_label.setVisible(not base_label.isVisible()))
        header.addWidget(details)
        layout.addWidget(base_label)

        detail = self.diff or json.dumps(self.arguments, indent=2, ensure_ascii=False)
        self.detail_view = QTextBrowser()
        self.detail_view.setObjectName("approvalDiff")
        self.detail_view.setHtml(render_diff_html(detail))
        lines = detail.count("\n") + 1
        self.detail_view.setFixedHeight(min(260, max(60, lines * 18 + 16)))
        layout.addWidget(self.detail_view)

        row = QHBoxLayout()
        self._action_row = row
        self.review_button = None
        if not command:
            self.review_button = QPushButton("Revisar diff")
            self.review_button.clicked.connect(self._review_diff)
            row.addWidget(self.review_button, 1)
        self.reject_button = QPushButton("Rechazar  (N)")
        self.reject_button.setProperty("variant", "danger")
        self.reject_button.setDefault(True)
        self.reject_button.clicked.connect(lambda: self._choose(False))
        self.approve_button = QPushButton("Permitir una vez (Y)" if command else "Aprobar una vez (Y)")
        self.approve_button.setProperty("variant", "primary")
        self.approve_button.clicked.connect(lambda: self._choose(True))
        row.addWidget(self.approve_button, 1)
        self.always_button = None
        if command:
            self.always_button = QPushButton("Permitir siempre este comando")
            self.always_button.setToolTip("Solo este argv, ejecutable/hash, cwd y perfil en este proyecto. Revocable en Ajustes.")
            self.always_button.clicked.connect(lambda: self._choose("always"))
            layout.addWidget(self.always_button)
        row.addWidget(self.reject_button, 1)
        layout.addLayout(row)

    def keyPressEvent(self, event) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QPlainTextEdit, QLineEdit)):
            super().keyPressEvent(event)
            return
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and not self._decided:
            key = event.key()
            if key == Qt.Key.Key_Y:
                self._choose(True)
                event.accept()
                return
            if key in (Qt.Key.Key_N, Qt.Key.Key_Escape):
                self._choose(False)
                event.accept()
                return
        super().keyPressEvent(event)

    def _review_diff(self):
        from PySide6.QtWidgets import QDialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Revisar cambios propuestos")
        dialog.resize(900, 620)
        box = QVBoxLayout(dialog)
        description = QLabel("Esta vista es de lectura. Aprobar y rechazar siguen en la tarjeta original.")
        description.setWordWrap(True)
        box.addWidget(description)
        view = QTextBrowser()
        view.setObjectName("approvalDiff")
        view.setHtml(render_diff_html(self.diff))
        box.addWidget(view, 1)
        close = QPushButton("Volver a la conversación")
        close.clicked.connect(dialog.close)
        box.addWidget(close)
        dialog.show()

    def set_compact(self, compact):
        self._compact_mode = compact
        narrow = compact or self.width() < 560
        direction = QBoxLayout.Direction.TopToBottom if self.width() < 310 else QBoxLayout.Direction.LeftToRight
        state = (narrow, direction)
        if getattr(self, "_applied_compact_state", None) == state:
            return
        self._applied_compact_state = state
        command = self.arguments.get("approval_kind") == "command"
        self._base_details.setText("Base" if narrow else "Identidad y base")
        self.detail_view.setVisible(not self._decided and (command or not narrow))
        self.approve_button.setText(("Una vez" if command else "Aprobar") if narrow else
                                   ("Permitir una vez (Y)" if command else "Aprobar una vez (Y)"))
        self.reject_button.setText("Rechazar" if narrow else "Rechazar (N)")
        if self.review_button is not None:
            self.review_button.setText("Ver diff" if narrow else "Revisar diff")
        self._action_row.setDirection(direction)
        self._header_row.setDirection(direction)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_compact(self._compact_mode)

    def _choose(self, approved: bool | str) -> None:
        if self._decided:
            return
        self._decided = True
        self.approve_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        if self.always_button is not None:
            self.always_button.setEnabled(False)
        self.status_badge.setText("AUTORIZADO · comando exacto" if approved == "always" else "APROBADO ✓" if approved else "RECHAZADO ✗")
        self.setProperty("decision", "approved" if approved else "rejected")
        self._collapse_decided(approved=bool(approved))
        theme.repolish(self)
        for child in self.findChildren(QLabel):
            theme.repolish(child)
        self.decision_made.emit(approved)

    def _collapse_decided(self, *, approved: bool = False) -> None:
        """Hide approved cards (the ToolCard already records execution) and compact rejected/expired ones."""
        self._decided_expanded = False
        self.detail_view.hide()
        self.approve_button.hide()
        self.reject_button.hide()
        if self.always_button is not None:
            self.always_button.hide()
        if self.review_button is not None:
            self.review_button.hide()
        if hasattr(self, "_path_label"):
            self._path_label.hide()
        self._base_details.hide()
        if approved:
            self.hide()
            return
        if hasattr(self, "_title_label"):
            self._title_label.setText("Propuesta rechazada")
        if not hasattr(self, "_toggle_details_btn"):
            btn = QPushButton("detalles ▸", self)
            btn.setProperty("variant", "ghost")
            def _toggle():
                self._decided_expanded = not self._decided_expanded
                self.detail_view.setVisible(self._decided_expanded)
                btn.setText("ocultar ▾" if self._decided_expanded else "detalles ▸")
            btn.clicked.connect(_toggle)
            self._header_row.addWidget(btn)
            self._toggle_details_btn = btn

    def expire(self) -> None:
        if self._decided:
            return
        self._decided = True
        self.approve_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        if self.always_button is not None:
            self.always_button.setEnabled(False)
        self.status_badge.setText("TURNO TERMINADO · propuesta sin aplicar")
        self._collapse_decided()


class ToolCard(QFrame):
    """Compact tool-call card with expandable details."""

    def __init__(self, tool_name: str, arguments: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("toolCard")
        self.setProperty("state", "running")
        self._expanded = False
        self._tool_name = tool_name
        self._arguments = arguments
        self._result: str | None = None
        self._success = True
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        top = QHBoxLayout()
        presentation = present_tool(self._tool_name, self._arguments)
        self.header_label = QLabel(presentation["title"])
        self.header_label.setTextFormat(Qt.TextFormat.PlainText)
        self.header_label.setObjectName("toolTitle")
        top.addWidget(self.header_label)
        self.status_label = QLabel("ejecutando…")
        self.status_label.setObjectName("toolStatus")
        top.addWidget(self.status_label)
        top.addStretch(1)
        self.expand_button = QPushButton("detalles ▸")
        self.expand_button.setProperty("variant", "ghost")
        self.expand_button.clicked.connect(self._toggle_expand)
        top.addWidget(self.expand_button)
        layout.addLayout(top)

        self.args_label = QLabel(presentation["summary"])
        self.args_label.setTextFormat(Qt.TextFormat.PlainText)
        self.args_label.setObjectName("toolArgs")
        self.args_label.setWordWrap(True)
        self.args_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.args_label)

        self.detail_area = QPlainTextEdit()
        self.detail_area.setObjectName("monoView")
        self.detail_area.setReadOnly(True)
        self.detail_area.setVisible(False)
        self.detail_area.setMaximumHeight(220)
        self.detail_area.setPlainText("--- Herramienta ---\n" + self._tool_name + "\n\n--- Argumentos originales ---\n" + json.dumps(self._arguments, ensure_ascii=False, indent=2))
        layout.addWidget(self.detail_area)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self.detail_area.setVisible(self._expanded)
        self.expand_button.setText("ocultar ▾" if self._expanded else "detalles ▸")

    def set_result(self, success: bool, stdout: str = "", stderr: str = "", evidence: dict | None = None, *, cancelled: bool = False, error_code: str = "", returncode=None, presentation: dict | None = None, stdout_truncated=False, stderr_truncated=False) -> None:
        self._success = success
        self._result = stdout or stderr
        self.status_label.setText("■ detenida" if cancelled else "✓ ok" if success else "✗ falló")
        self.setProperty("state", "ok" if success else "fail")
        theme.repolish(self)
        view = presentation or present_tool(self._tool_name, self._arguments, {
            "success": success, "stdout": stdout, "stderr": stderr,
            "error_code": "CANCELLED" if cancelled else error_code, "returncode": returncode})
        self.header_label.setText(view["title"])
        self.args_label.setText(view["summary"])
        self.status_label.setText(view["status"])
        parts = ["--- Herramienta ---\n" + self._tool_name,
                 "--- Argumentos originales ---\n" + json.dumps(self._arguments, indent=2, ensure_ascii=False),
                 f"--- Resultado ---\nsuccess: {success}\nreturncode: {returncode}\nerror_code: {error_code}"]
        if stdout:
            parts.append("--- stdout" + (" · vista acotada a 4000 caracteres" if stdout_truncated else "") + f" ---\n{stdout}")
        if stderr:
            parts.append("--- stderr" + (" · vista acotada a 2000 caracteres" if stderr_truncated else "") + f" ---\n{stderr}")
        if evidence:
            parts.append(f"--- evidence ---\n{json.dumps(evidence, indent=2, ensure_ascii=False)}")
        self.detail_area.setPlainText("\n\n".join(parts))


class MessageBubble(QFrame):
    """A finished message bubble (user or assistant)."""

    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(parent)
        self._is_user = is_user
        self._build(text)

    def _build(self, text: str) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        column = QVBoxLayout()
        column.setSpacing(3)
        author = QLabel("Tú" if self._is_user else "ISyCode IDE")
        author.setObjectName("bubbleAuthorUser" if self._is_user else "bubbleAuthor")
        body = AutoTextBrowser()
        if self._is_user:
            body.setObjectName("userBubble")
            body.setMarkdownHtml(html.escape(text).replace("\n", "<br>"))
            author.setAlignment(Qt.AlignmentFlag.AlignLeft)
            column.addWidget(author)
            column.addWidget(body)
            outer.addLayout(column, 4)
            outer.addStretch(1)
        else:
            body.setObjectName("assistantBody")
            body.setMarkdownHtml(_render_markdown(text))
            column.addWidget(author)
            column.addWidget(body)
            outer.addLayout(column, 5)
            outer.addStretch(1)


class StreamingAssistantBubble(QFrame):
    """Assistant bubble that renders streaming markdown and hosts tool cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buffer = ""
        self._reasoning_buffer = ""
        self._tool_cards: list[ToolCard] = []
        self._build()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(50)
        self._render_timer.timeout.connect(self.flush_text)

    def _build(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 2, 0, 2)
        self.main_layout.setSpacing(6)

        bubble = QFrame()
        bubble.setObjectName("assistantBubble")
        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(6)

        header = QHBoxLayout()
        avatar = QLabel()
        avatar.setPixmap(QPixmap(str(Path(__file__).parent.parent / "assets" / "isycode_64x64.png")).scaled(
            32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        avatar.setFixedSize(36, 36)
        header.addWidget(avatar)
        self.header_label = QLabel("ISyCode IDE")
        self.header_label.setObjectName("bubbleAuthor")
        header.addWidget(self.header_label)
        header.addStretch(1)
        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.setProperty("variant", "ghost")
        self.copy_btn.setToolTip("Copiar la respuesta en Markdown")
        self.copy_btn.clicked.connect(self._copy_response)
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: self.copy_btn.setText("Copiar"))
        header.addWidget(self.copy_btn)
        inner.addLayout(header)

        self.reasoning_toggle = QPushButton("▸ Razonamiento del modelo · recibiendo…")
        self.reasoning_toggle.setCheckable(True)
        self.reasoning_toggle.setProperty("variant", "ghost")
        self.reasoning_toggle.setToolTip("Texto devuelto por el provider, separado de la respuesta. No autoriza acciones ni acredita resultados.")
        self.reasoning_toggle.setVisible(False)
        inner.addWidget(self.reasoning_toggle)
        self.reasoning_body = QPlainTextEdit()
        self.reasoning_body.setReadOnly(True)
        self.reasoning_body.setMaximumHeight(220)
        self.reasoning_body.setMinimumHeight(120)
        self.reasoning_body.setAccessibleName("Razonamiento devuelto por el provider")
        self.reasoning_body.setVisible(False)
        self.reasoning_toggle.toggled.connect(self.reasoning_body.setVisible)
        inner.addWidget(self.reasoning_body)

        self.content_browser = AutoTextBrowser()
        self.content_browser.setObjectName("assistantBody")
        inner.addWidget(self.content_browser)
        self.main_layout.addWidget(bubble)

        self.tools_toggle = QPushButton("▾ Herramientas")
        self.tools_toggle.setCheckable(True)
        self.tools_toggle.setChecked(True)
        self.tools_toggle.setProperty("variant", "ghost")
        self.tools_toggle.setStyleSheet("text-align: left; padding: 3px 8px; color: #94a3b8; font-size: 11px;")
        self.tools_toggle.setVisible(False)
        self.main_layout.addWidget(self.tools_toggle)

        self.tools_box = QWidget(self)
        self.tools_container = QVBoxLayout(self.tools_box)
        self.tools_container.setContentsMargins(12, 0, 0, 0)
        self.tools_container.setSpacing(4)
        self.tools_toggle.toggled.connect(self._on_tools_toggled)
        self.main_layout.addWidget(self.tools_box)

    def _on_tools_toggled(self, expanded: bool) -> None:
        self.tools_box.setVisible(expanded)
        self._refresh_tools_toggle_label()

    def _refresh_tools_toggle_label(self) -> None:
        n = len(self._tool_cards)
        if n == 0:
            self.tools_toggle.setVisible(False)
            return
        ok = sum(1 for c in self._tool_cards if c._success and c._result is not None)
        fail = sum(1 for c in self._tool_cards if not c._success and c._result is not None)
        arrow = "▾" if self.tools_toggle.isChecked() else "▸"
        summary = f"{arrow} {n} paso{'s' if n != 1 else ''} de herramientas"
        if ok or fail:
            parts = []
            if ok:
                parts.append(f"{ok} ok")
            if fail:
                parts.append(f"{fail} falló" if fail == 1 else f"{fail} fallaron")
            summary += " (" + " · ".join(parts) + ")"
        self.tools_toggle.setText(summary)
        self.tools_toggle.setVisible(n >= 2)

    def collapse_tools(self) -> None:
        if len(self._tool_cards) >= 2:
            self.tools_toggle.setChecked(False)
            self._refresh_tools_toggle_label()

    def append_chunk(self, chunk: str) -> None:
        first = not self._buffer
        self._buffer += chunk
        if first:
            self.flush_text()
        elif not self._render_timer.isActive():
            self._render_timer.start()

    def flush_text(self) -> None:
        self._render_timer.stop()
        self.content_browser.setMarkdownHtml(_render_markdown(self._buffer))

    def append_reasoning(self, text: str) -> None:
        self.reasoning_toggle.setVisible(True)
        self._reasoning_buffer += text
        cursor = self.reasoning_body.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.reasoning_body.setTextCursor(cursor)

    def finish_reasoning(self, status="turno cerrado · puede ser parcial") -> None:
        if self._reasoning_buffer:
            self.reasoning_toggle.setText("▸ Razonamiento del modelo · " + status)

    def _copy_response(self) -> None:
        QGuiApplication.clipboard().setText(self._buffer)
        self.copy_btn.setText("Copiado ✓")
        self._copy_timer.start(1500)

    def add_tool_card(self, tool_name: str, arguments: dict) -> ToolCard:
        card = ToolCard(tool_name, arguments, self)
        self.tools_container.addWidget(card)
        self._tool_cards.append(card)
        self._refresh_tools_toggle_label()
        return card

    def get_last_tool_card(self) -> ToolCard | None:
        return self._tool_cards[-1] if self._tool_cards else None


class EmptyState(QWidget):
    """Shown while the conversation is empty."""

    provider_setup_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        layout = QVBoxLayout(self)
        layout.addStretch(2)
        title = QLabel("ISYCODE")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.subtitle = QLabel("El modelo propone · ISyCode IDE autoriza y ejecuta")
        self.subtitle.setObjectName("emptySubtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)
        self.configure_button = QPushButton("Configurar provider")
        self.configure_button.setProperty("variant", "primary")
        self.configure_button.clicked.connect(self.provider_setup_requested.emit)
        layout.addWidget(self.configure_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(18)
        keys = QLabel(
            "Enter enviar  ·  Shift+Enter nueva línea  ·  Esc detener<br>"
            "Ctrl+K comandos  ·  Ctrl+N nueva sesión  ·  Ctrl+B workspace  ·  Ctrl+` paneles")
        keys.setObjectName("emptyKeys")
        keys.setWordWrap(True)
        self.keys = keys
        keys.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(keys)
        layout.addStretch(3)


class _ChatScrollBar(QScrollBar):
    """Vertical scrollbar that notifies ChatPanel even if setValue(0) lands before layout settles."""

    def __init__(self, on_external_set, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self._on_external_set = on_external_set

    def setValue(self, value: int) -> None:
        self._on_external_set(value)
        super().setValue(value)


class ChatPanel(QWidget):
    """Chat with empty state, smart auto-scroll, approvals and composer."""

    prompt_submitted = Signal(str)
    provider_setup_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._streaming_bubble: StreamingAssistantBubble | None = None
        self._active_approval_card: ApprovalCard | None = None
        self._composer_notices: dict[str, QFrame] = {}
        self._user_scrolled_up = False
        self._auto_scrolling = False
        self._compact = False
        self._build()
        self._progress_phase = ""
        self._progress_tool = ""
        self._progress_step = 0
        self._progress_max_steps = 0
        self._activity_at = self._phase_at = time.monotonic()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._render_progress)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.empty_state = EmptyState()
        self.empty_state.provider_setup_requested.connect(self.provider_setup_requested.emit)
        self.stack.addWidget(self.empty_state)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("chatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBar(_ChatScrollBar(self._on_external_scroll_set, self.scroll))
        self.messages_container = QWidget()
        self.messages_container.setObjectName("chatScrollBody")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(28, 20, 28, 20)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch(1)
        self.scroll.setWidget(self.messages_container)
        self.stack.addWidget(self.scroll)
        layout.addWidget(self.stack, stretch=1)

        vbar = self.scroll.verticalScrollBar()
        vbar.valueChanged.connect(self._on_scroll_changed)
        vbar.rangeChanged.connect(self._on_range_changed)

        self.scroll_bottom_btn = QPushButton("↓  Ir al final", self)
        self.scroll_bottom_btn.setObjectName("scrollBottom")
        self.scroll_bottom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scroll_bottom_btn.clicked.connect(self._scroll_to_bottom_forced)
        self.scroll_bottom_btn.setFixedSize(120, 28)
        layout.addWidget(self.scroll_bottom_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self.scroll_bottom_btn.hide()

        composer = QFrame()
        self.composer = composer
        composer.setObjectName("composer")
        c_layout = QVBoxLayout(composer)
        c_layout.setContentsMargins(28, 10, 28, 12)
        c_layout.setSpacing(6)

        self.composer_notices_container = QWidget(composer)
        self.composer_notices_container.setObjectName("composerNotices")
        self._composer_notices_layout = QVBoxLayout(self.composer_notices_container)
        self._composer_notices_layout.setContentsMargins(0, 0, 0, 0)
        self._composer_notices_layout.setSpacing(4)
        self.composer_notices_container.hide()
        c_layout.addWidget(self.composer_notices_container)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = PromptComposer(self)
        self.input.submit_requested.connect(self._submit)
        self.input.textChanged.connect(self._update_stats)
        input_row.addWidget(self.input, stretch=1)
        self.send_button = QPushButton("Enviar")
        self.send_button.setProperty("variant", "primary")
        self.send_button.setFixedSize(QSize(84, PromptComposer.MIN_H))
        self.send_button.clicked.connect(self._submit)
        input_row.addWidget(self.send_button, alignment=Qt.AlignmentFlag.AlignBottom)
        c_layout.addLayout(input_row)

        status_row = QHBoxLayout()
        self.status_label = QLabel("● Listo")
        self.status_label.setObjectName("composerStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status_row.addWidget(self.status_label, 1)
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("composerStats")
        status_row.addWidget(self.stats_label)
        status_row.addStretch(1)
        self.stop_button = QPushButton("Detener  Esc")
        self.stop_button.setProperty("variant", "danger")
        self.stop_button.setEnabled(False)
        status_row.addWidget(self.stop_button)
        c_layout.addLayout(status_row)
        layout.addWidget(composer)

        self._set_state("ready", "● Listo")

    # --- layout helpers ---------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        """Change spacing only; keep the same transcript, cards and input draft."""
        self._compact = compact
        for card in self.findChildren(ApprovalCard):
            card.set_compact(compact)
        inset = 12 if compact else 24
        self.messages_layout.setContentsMargins(inset, 16, inset, 16)
        self.composer.layout().setContentsMargins(inset, 10, inset, 12)
        self.stats_label.setVisible(not compact)
        self.empty_state.keys.setText("Enter enviar · Shift+Enter nueva línea\nEsc detener" if compact else
                                      "Enter enviar · Shift+Enter nueva línea · Esc detener\nCtrl+K comandos · Ctrl+N conversación · Ctrl+B archivos")
        self.input.setPlaceholderText("Escribe a ISyCode…" if compact else "Pide un cambio o haz una pregunta…")

    def _show_conversation(self) -> None:
        if self.stack.currentWidget() is not self.scroll:
            self.stack.setCurrentWidget(self.scroll)

    def _insert(self, widget: QWidget) -> None:
        self._show_conversation()
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, widget)

    # --- scrolling ----------------------------------------------------------

    def _set_scroll_value(self, value: int) -> None:
        self._auto_scrolling = True
        try:
            self.scroll.verticalScrollBar().setValue(value)
        finally:
            self._auto_scrolling = False

    def _on_external_scroll_set(self, value: int) -> None:
        if self._auto_scrolling:
            return
        vbar = self.scroll.verticalScrollBar()
        if vbar.maximum() == 0 and value == 0 and self.messages_layout.count() > 1:
            self._user_scrolled_up = True

    def _on_scroll_changed(self, value: int) -> None:
        away = self.scroll.verticalScrollBar().maximum() - value > 40
        self._user_scrolled_up = away
        self.scroll_bottom_btn.setVisible(away)

    def _on_range_changed(self, _min: int, maximum: int) -> None:
        # Content grew: keep following unless the user scrolled away.
        if not self._user_scrolled_up:
            self._set_scroll_value(maximum)
        else:
            away = maximum - self.scroll.verticalScrollBar().value() > 40
            self.scroll_bottom_btn.setVisible(away)

    def _scroll_to_bottom(self) -> None:
        if not self._user_scrolled_up:
            vbar = self.scroll.verticalScrollBar()
            self._set_scroll_value(vbar.maximum())

    def _scroll_to_bottom_forced(self) -> None:
        self._user_scrolled_up = False
        self.scroll_bottom_btn.hide()
        vbar = self.scroll.verticalScrollBar()
        self._set_scroll_value(vbar.maximum())

    # --- composer -----------------------------------------------------------

    def _update_stats(self) -> None:
        chars = len(self.input.toPlainText())
        self.stats_label.setText(f"·  {chars} car. · ~{chars // 4} tokens" if chars else "")

    def _submit(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.prompt_submitted.emit(text)

    def _set_state(self, state: str, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        theme.repolish(self.status_label)

    # --- composer notices ---------------------------------------------------

    def set_composer_notice(
        self,
        key: str,
        text: str,
        action_label: str | None = None,
        callback=None,
    ) -> QFrame:
        """Show or update a persistent notice anchored right above the prompt composer."""
        if key in self._composer_notices:
            self.clear_composer_notice(key)
        notice = QFrame(self.composer_notices_container)
        notice.setObjectName("composerNotice")
        notice.setStyleSheet(
            f"QFrame#composerNotice {{ background: {theme.SURFACE_2}; "
            f"border: 1px solid {theme.WARN}; border-radius: 8px; }}"
        )
        row = QHBoxLayout(notice)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        label = QLabel(text, notice)
        label.setObjectName("composerNoticeText")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
        row.addWidget(label, stretch=1)
        notice.notice_label = label
        notice.action_button = None
        if action_label:
            btn = QPushButton(action_label, notice)
            btn.setProperty("variant", "primary")
            if callable(callback):
                btn.clicked.connect(callback)
            row.addWidget(btn)
            notice.action_button = btn
        self._composer_notices[key] = notice
        self._composer_notices_layout.addWidget(notice)
        self.composer_notices_container.show()
        return notice

    def clear_composer_notice(self, key: str) -> bool:
        """Remove a persistent composer notice by key."""
        notice = self._composer_notices.pop(key, None)
        if notice is None:
            return False
        self._composer_notices_layout.removeWidget(notice)
        notice.hide()
        notice.deleteLater()
        if not self._composer_notices:
            self.composer_notices_container.hide()
        return True

    # --- approvals ----------------------------------------------------------

    def add_approval_card(self, approval_id: str, tool_name: str, arguments: dict, diff: str) -> ApprovalCard:
        card = ApprovalCard(approval_id, tool_name, arguments, diff, self)
        card.set_compact(self._compact)
        self._active_approval_card = card
        self._insert(card)
        self.set_agent_progress({"phase": "approval", "tool": tool_name})
        self._scroll_to_bottom_forced()
        focus = QApplication.focusWidget()
        typing_in_input = (
            isinstance(focus, (QPlainTextEdit, QLineEdit))
            or self.input.hasFocus()
            or bool(self.input.toPlainText().strip())
        )
        if not typing_in_input:
            card.reject_button.setFocus()
        return card

    def active_approval_card(self) -> ApprovalCard | None:
        return self._active_approval_card

    # --- public message API ---------------------------------------------------

    def add_user_message(self, text: str) -> None:
        self._insert(MessageBubble(text, is_user=True))
        self._scroll_to_bottom_forced()

    def start_assistant_stream(self) -> None:
        self._streaming_bubble = StreamingAssistantBubble(self)
        self._insert(self._streaming_bubble)
        self.set_status_working()
        self._scroll_to_bottom()

    def append_chunk(self, chunk: str) -> None:
        if self._streaming_bubble is None or self._streaming_bubble._tool_cards:
            if self._streaming_bubble is not None:
                self._streaming_bubble.flush_text()
                self._streaming_bubble.finish_reasoning("paso previo")
                self._streaming_bubble.collapse_tools()
            self.start_assistant_stream()
        self._streaming_bubble.append_chunk(chunk)
        self._scroll_to_bottom()

    def append_reasoning(self, text: str) -> None:
        if self._streaming_bubble is None:
            self.start_assistant_stream()
        self._streaming_bubble.append_reasoning(text)
        self._scroll_to_bottom()

    def add_tool_call(self, tool_name: str, arguments: dict) -> ToolCard | None:
        if self._streaming_bubble is None:
            self.start_assistant_stream()
        card = self._streaming_bubble.add_tool_card(tool_name, arguments)
        self._scroll_to_bottom()
        return card

    def end_assistant_stream(self, reasoning_status="turno cerrado · puede ser parcial") -> None:
        if self._streaming_bubble is not None:
            self._streaming_bubble.flush_text()
            self._streaming_bubble.finish_reasoning(reasoning_status)
            self._streaming_bubble.collapse_tools()
        self._streaming_bubble = None
        self.set_status_ready()
        self._scroll_to_bottom()

    def add_system_message(self, text: str) -> None:
        label = QLabel(html.escape(text))
        label.setObjectName("systemMessage")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._insert(label)
        self._scroll_to_bottom()

    def add_recovery_card(
        self,
        title: str,
        detail: str,
        actions: list[tuple[str, callable]] | None = None,
        model_switcher: tuple[list[str], str, callable] | None = None,
    ) -> QFrame:
        """Actionable recovery card when a turn fails, cancels, or hits a workspace guard."""
        from PySide6.QtWidgets import QComboBox
        card = QFrame(self)
        card.setObjectName("approvalCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(8)
        hdr = QLabel(title)
        hdr.setObjectName("approvalTitle")
        hdr.setTextFormat(Qt.TextFormat.PlainText)
        hdr.setWordWrap(True)
        box.addWidget(hdr)
        body = QLabel(detail)
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        box.addWidget(body)
        if model_switcher is not None:
            models, current_model, on_retry_model = model_switcher
            sw_lbl = QLabel("Cambiar modelo del mismo provider y reintentar:")
            sw_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            sw_lbl.setWordWrap(True)
            box.addWidget(sw_lbl)
            combo = QComboBox(card)
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.setMinimumWidth(140)
            ordered = [m for m in models if m != current_model]
            if current_model and current_model not in ordered:
                ordered.append(current_model)
            for m in ordered:
                combo.addItem(m)
            if ordered:
                combo.setCurrentIndex(0)
            elif current_model:
                combo.setCurrentText(current_model)
            card.model_combo = combo
            box.addWidget(combo)
            sw_btn = QPushButton("Cambiar modelo y reintentar")
            sw_btn.setProperty("variant", "primary")
            sw_btn.clicked.connect(lambda _=False, c=combo, cb=on_retry_model: cb(c.currentText().strip()))
            card.switch_retry_button = sw_btn
            box.addWidget(sw_btn)
        if actions:
            row = QHBoxLayout()
            row.setSpacing(8)
            for idx, (label, callback) in enumerate(actions):
                btn = QPushButton(label)
                if idx == 0 and model_switcher is None:
                    btn.setProperty("variant", "primary")
                btn.clicked.connect(callback)
                row.addWidget(btn)
            row.addStretch(1)
            box.addLayout(row)
        self._insert(card)
        self._scroll_to_bottom()
        return card

    def set_status_working(self) -> None:
        if not self._progress_timer.isActive():
            self.set_agent_progress({"phase": "provider_wait", "step": 1})
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.input.setReadOnly(True)

    def set_status_ready(self) -> None:
        self._progress_timer.stop()
        self._progress_phase = ""
        self._set_state("ready", "● Listo")
        self.send_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.stop_button.setText("Detener  Esc")
        self.input.setReadOnly(False)
        self.input.setFocus()

    def set_status_error(self, message: str) -> None:
        self._progress_timer.stop()
        self._progress_phase = ""
        self._set_state("error", f"● Error: {message}")
        self.send_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.input.setReadOnly(False)

    def set_agent_progress(self, event: dict) -> None:
        phase = event.get("phase", "provider_wait")
        if self._progress_phase == "stopping" and phase != "stopping":
            return
        now = time.monotonic()
        tool = event.get("tool", "")
        if (phase, tool) != (self._progress_phase, self._progress_tool):
            self._phase_at = now
        self._activity_at = now
        self._progress_phase, self._progress_tool = phase, tool
        self._progress_step = event.get("step", self._progress_step)
        self._progress_max_steps = event.get("max_steps", self._progress_max_steps)
        self._progress_timer.start()
        self._render_progress()

    def _render_progress(self) -> None:
        labels = {"provider_wait": "Esperando respuesta del modelo",
                  "project": "Preparando la vista del proyecto",
                  "provider_activity": "Recibiendo actividad del modelo",
                  "tool_arguments": "Recibiendo una llamada de herramienta",
                  "text": "Recibiendo texto",
                  "reasoning": "Recibiendo razonamiento del modelo",
                  "finalizing": "Solicitando respuesta final · descubrimiento repetido",
                  "tool": f"Ejecutando {self._progress_tool}",
                  "approval": f"Esperando tu aprobación · {self._progress_tool}",
                  "stopping": "Deteniendo el agente"}
        phase = self._progress_phase
        now = time.monotonic()
        elapsed = int(now - self._phase_at)
        step = f" · paso {self._progress_step}/{self._progress_max_steps}" if self._progress_max_steps else ""
        quiet = int(now - self._activity_at)
        waiting = f" · sin nuevos eventos {quiet}s" if quiet >= 15 and phase != "approval" else ""
        self._set_state("working", f"● {labels.get(phase, 'Preparando turno')} · {elapsed}s{step}{waiting}")
        self.status_label.setToolTip("Este estado refleja eventos recibidos del agente. La ausencia de texto no demuestra que el modelo esté pensando ni que haya terminado.")

    def set_status_stopping(self) -> None:
        self.set_agent_progress({"phase": "stopping"})
        self.stop_button.setEnabled(False)
        self.stop_button.setText("Deteniendo…")

    def clear_log(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._streaming_bubble = None
        self._active_approval_card = None
        self.stack.setCurrentWidget(self.empty_state)
