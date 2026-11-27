"""Editor panel: VS Code Dark+ syntax-highlighted code editor with line numbers,
multi-language lexing via Pygments, and boundary-checked persistence."""

from __future__ import annotations

import re
import hashlib
from pathlib import Path

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QPainter, QSyntaxHighlighter,
                            QTextCharFormat, QTextFormat)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                                QPushButton, QTabBar, QTextEdit, QVBoxLayout, QWidget)
from pygments.lexers import (PythonLexer, TextLexer, get_lexer_by_name,
                             get_lexer_for_filename)
from pygments.token import Token

from .. import theme


class LineNumberArea(QWidget):
    """Gutter widget displaying line numbers on the left of CodeEditor."""

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self.code_editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    """Editor widget featuring line numbers, active line highlight, and 4-space tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        self.update_line_number_area_width(0)
        self.highlight_current_line()

        # 4-space tab stop
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)

    def line_number_area_width(self) -> int:
        digits = 1
        m = max(1, self.blockCount())
        while m >= 10:
            m //= 10
            digits += 1
        space = 16 + self.fontMetrics().horizontalAdvance("9") * max(2, digits)
        return space

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def highlight_current_line(self):
        extra_selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            line_color = QColor("#1b1f2b")
            selection.format.setBackground(line_color)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        self.setExtraSelections(extra_selections)

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#13151c"))

        # Right divider line
        painter.setPen(QColor("#242834"))
        painter.drawLine(event.rect().right(), event.rect().top(),
                         event.rect().right(), event.rect().bottom())

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        current_block = self.textCursor().blockNumber()
        num_font = self.font()
        num_font.setPointSize(10)
        painter.setFont(num_font)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                is_current = (block_number == current_block)
                painter.setPen(QColor("#c6c6c6" if is_current else "#4d5361"))
                painter.drawText(
                    0, top, self.line_number_area.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, number,
                )

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1


class CodeHighlighter(QSyntaxHighlighter):
    """VS Code Dark+ syntax highlighter supporting Python, Markdown, Rust, Zig, JS, etc."""

    VSCODE_COLORS = {
        # Keywords
        Token.Keyword: ("#c586c0", True, False),             # control flow: purple
        Token.Keyword.Declaration: ("#569cd6", True, False), # def, class, const, fn: blue
        Token.Keyword.Namespace: ("#c586c0", True, False),   # import, from, use: purple
        Token.Keyword.Constant: ("#4fc1ff", False, False),   # True, False, None, null: cyan
        Token.Keyword.Type: ("#4ec9b0", False, False),       # types (int, str, bool, void): teal
        
        # Functions & Methods
        Token.Name.Function: ("#dcdcaa", False, False),      # yellow
        Token.Name.Function.Magic: ("#569cd6", False, False),# blue
        Token.Name.Class: ("#4ec9b0", True, False),          # teal bold
        Token.Name.Builtin: ("#4ec9b0", False, False),       # teal
        Token.Name.Builtin.Pseudo: ("#569cd6", False, False),# self, cls, this: blue
        
        # Variables & Properties
        Token.Name.Variable: ("#9cdcfe", False, False),      # light blue
        Token.Name.Attribute: ("#9cdcfe", False, False),     # light blue
        Token.Name.Tag: ("#569cd6", False, False),           # blue
        Token.Name.Decorator: ("#dcdcaa", False, False),     # yellow (@decorator)
        Token.Name.Label: ("#9cdcfe", False, False),
        
        # Strings & Chars
        Token.String: ("#ce9178", False, False),             # coral/orange
        Token.String.Char: ("#ce9178", False, False),
        Token.String.Doc: ("#6a9955", False, True),          # docstrings: green italic
        Token.String.Escape: ("#d7ba7d", False, False),      # escape sequences: gold
        Token.String.Interpol: ("#9cdcfe", False, False),    # f-string interpolation
        
        # Numbers
        Token.Number: ("#b5cea8", False, False),             # light green
        
        # Comments
        Token.Comment: ("#6a9955", False, True),             # green italic
        Token.Comment.Preproc: ("#c586c0", False, False),    # preprocessor macros
        
        # Operators & Punctuation
        Token.Operator: ("#d4d4d4", False, False),
        Token.Operator.Word: ("#569cd6", True, False),       # and, or, not, is, in
        Token.Punctuation: ("#d4d4d4", False, False),
        
        # Markdown & Documentation
        Token.Generic.Heading: ("#569cd6", True, False),     # blue bold (# Heading)
        Token.Generic.Subheading: ("#4ec9b0", True, False),  # teal bold (## Subheading)
        Token.Generic.Strong: ("#dcdcaa", True, False),      # yellow bold (**bold**)
        Token.Generic.Emph: ("#ce9178", False, True),        # coral italic (*italic*)
        Token.Generic.Prompt: ("#4fc1ff", False, False),     # cyan (>_)
        Token.Generic.Inserted: ("#b5cea8", False, False),   # green
        Token.Generic.Deleted: ("#f44747", False, False),    # red
        Token.Literal: ("#ce9178", False, False),
    }

    def __init__(self, document, filename: str = ""):
        super().__init__(document)
        self._format_map: dict[object, QTextCharFormat] = {}
        self._filename = filename
        self._lexer = self._pick_lexer(filename)
        self._init_formats()

    def _init_formats(self) -> None:
        for tok, (color, bold, italic) in self.VSCODE_COLORS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if italic:
                fmt.setFontItalic(True)
            self._format_map[tok] = fmt

    def _pick_lexer(self, filename: str):
        if not filename:
            return PythonLexer()
        lower = filename.lower()
        if lower.endswith((".md", ".markdown", ".mdown")):
            return get_lexer_by_name("markdown")
        if lower.endswith((".py", ".pyw")):
            return PythonLexer()
        if lower.endswith((".json", ".jsonl")):
            return get_lexer_by_name("json")
        if lower.endswith((".yaml", ".yml")):
            return get_lexer_by_name("yaml")
        if lower.endswith((".toml", ".ini")):
            return get_lexer_by_name("ini")
        if lower.endswith((".sh", ".bash", ".zsh")):
            return get_lexer_by_name("bash")
        if lower.endswith((".js", ".jsx", ".mjs")):
            return get_lexer_by_name("javascript")
        if lower.endswith((".ts", ".tsx")):
            return get_lexer_by_name("typescript")
        if lower.endswith((".rs",)):
            return get_lexer_by_name("rust")
        if lower.endswith((".zig",)):
            return get_lexer_by_name("zig")
        if lower.endswith((".c", ".h")):
            return get_lexer_by_name("c")
        if lower.endswith((".cpp", ".hpp", ".cc")):
            return get_lexer_by_name("cpp")
        try:
            return get_lexer_for_filename(filename)
        except Exception:
            return TextLexer()

    def set_file(self, filename: str) -> None:
        self._filename = filename
        self._lexer = self._pick_lexer(filename)
        self.rehighlight()

    def _get_format(self, token_type):
        while token_type:
            if token_type in self._format_map:
                return self._format_map[token_type]
            token_type = token_type.parent
        return None

    def highlightBlock(self, text: str) -> None:
        if not text:
            return

        pos = 0
        for token_type, val in self._lexer.get_tokens(text):
            length = len(val)
            fmt = self._get_format(token_type)
            if fmt:
                self.setFormat(pos, length, fmt)
            pos += length

        # Additional regex rules for Markdown to match VS Code rich preview/editing
        if self._filename.lower().endswith((".md", ".markdown", ".mdown")):
            # Markdown header lines (# ...)
            stripped = text.lstrip()
            if stripped.startswith("#"):
                h_fmt = QTextCharFormat()
                h_fmt.setForeground(QColor("#569cd6"))
                h_fmt.setFontWeight(QFont.Weight.Bold)
                self.setFormat(0, len(text), h_fmt)
            # Inline backticks `code`
            for m in re.finditer(r"`([^`]+)`", text):
                c_fmt = QTextCharFormat()
                c_fmt.setForeground(QColor("#ce9178"))
                self.setFormat(m.start(), m.end() - m.start(), c_fmt)
            # Bold **text**
            for m in re.finditer(r"\*\*([^*]+)\*\*", text):
                b_fmt = QTextCharFormat()
                b_fmt.setForeground(QColor("#dcdcaa"))
                b_fmt.setFontWeight(QFont.Weight.Bold)
                self.setFormat(m.start(), m.end() - m.start(), b_fmt)


# Backward-compatible alias for existing imports
PythonHighlighter = CodeHighlighter


class EditorPanel(QWidget):
    content_changed = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.current_path: Path | None = None
        self.snapshot: str = ""
        self._buffers: dict[str, dict] = {}
        self._switching_tab = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.file_tabs = QTabBar()
        self.file_tabs.setDocumentMode(True)
        self.file_tabs.setTabsClosable(True)
        self.file_tabs.setExpanding(False)
        self.file_tabs.setMovable(True)
        self.file_tabs.currentChanged.connect(self._on_tab_selected)
        self.file_tabs.tabCloseRequested.connect(self._close_tab)
        self.file_tabs.hide()
        layout.addWidget(self.file_tabs)

        header = QHBoxLayout()
        self.file_badge = QLabel()
        self.file_badge.setFixedSize(22, 22)
        header.addWidget(self.file_badge)
        self.title_label = QLabel("Abre un archivo del árbol del proyecto")
        self.title_label.setObjectName("sectionTitle")
        header.addWidget(self.title_label, stretch=1)

        self.save_button = QPushButton("Guardar")
        self.save_button.setProperty("variant", "primary")
        self.save_button.setToolTip("Guardar cambios en disco")
        self.save_button.clicked.connect(self.save)
        self.save_button.setEnabled(False)
        header.addWidget(self.save_button)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Editor: Editor de código integrado con resaltado de sintaxis VS Code Dark+ y números de línea.\n"
            "Permite editar y guardar archivos del workspace de manera segura."
        )
        header.addWidget(self.help_button)
        layout.addLayout(header)

        self.editor = CodeEditor()
        self.editor.setObjectName("monoView")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setPlaceholderText("Haz doble clic en un archivo del árbol del proyecto para abrirlo y editarlo aquí.")
        self.highlighter = CodeHighlighter(self.editor.document())
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor, stretch=1)

        self.message_label = QLabel("")
        self.message_label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        layout.addWidget(self.message_label)

    def _rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.controller.working_dir)).replace("\\", "/")

    def _sync_current_buffer(self) -> None:
        if self.current_path is not None:
            key = str(self.current_path.resolve())
            if key in self._buffers:
                self._buffers[key]["text"] = self.editor.toPlainText()
                self._buffers[key]["snapshot"] = self.snapshot

    def _update_tab_label(self, key: str) -> None:
        buf = self._buffers.get(key)
        if not buf:
            return
        dirty = buf["text"] != buf["snapshot"]
        label = ("• " if dirty else "") + buf["path"].name
        for idx in range(self.file_tabs.count()):
            if self.file_tabs.tabData(idx) == key:
                self.file_tabs.setTabText(idx, label)
                break

    def _on_tab_selected(self, index: int) -> None:
        if self._switching_tab or index < 0:
            return
        key = self.file_tabs.tabData(index)
        buf = self._buffers.get(key)
        if not buf:
            return
        self._sync_current_buffer()
        self._switching_tab = True
        try:
            self.current_path = buf["path"]
            self.snapshot = buf["snapshot"]
            self.highlighter.set_file(buf["path"].name)
            self.editor.setPlainText(buf["text"])
            from ui.icons import file_icon
            self.file_badge.setPixmap(file_icon(buf["path"]).pixmap(22, 22))
            self.title_label.setText(buf["path"].name)
            self.title_label.setToolTip(buf["rel"])
            self.save_button.setEnabled(True)
            self.message_label.setText("")
        finally:
            self._switching_tab = False

    def _close_tab(self, index: int) -> None:
        key = self.file_tabs.tabData(index)
        self._buffers.pop(key, None)
        self.file_tabs.removeTab(index)
        if self.file_tabs.count() == 0:
            self.file_tabs.hide()
            self.current_path = None
            self.snapshot = ""
            self.title_label.setText("Abre un archivo del árbol del proyecto")
            self.file_badge.clear()
            self.editor.clear()
            self.save_button.setEnabled(False)
            self.message_label.setText("")
        else:
            self._on_tab_selected(self.file_tabs.currentIndex())

    def reset_workspace(self) -> None:
        self._switching_tab = True
        try:
            self._buffers.clear()
            while self.file_tabs.count():
                self.file_tabs.removeTab(0)
            self.file_tabs.hide()
            self.current_path = None
            self.snapshot = ""
            self.title_label.setText("Abre un archivo del árbol del proyecto")
            self.file_badge.clear()
            self.editor.clear()
            self.save_button.setEnabled(False)
            self.message_label.setText("")
        finally:
            self._switching_tab = False

    def open_file(self, path: str | Path) -> bool:
        path = Path(path)
        try:
            rel = self._rel(path)
        except ValueError:
            self.message_label.setText("File is outside the workspace boundary")
            return False
        result = self.controller.execute_tool("read", {"path": rel})
        if not result.success:
            self.message_label.setText(result.stderr)
            return False
        self._sync_current_buffer()
        key = str(path.resolve())
        self._buffers[key] = {"path": path, "rel": rel, "snapshot": result.stdout, "text": result.stdout}
        self._switching_tab = True
        try:
            existing_idx = next((i for i in range(self.file_tabs.count()) if self.file_tabs.tabData(i) == key), -1)
            if existing_idx < 0:
                existing_idx = self.file_tabs.addTab(path.name)
                self.file_tabs.setTabData(existing_idx, key)
                self.file_tabs.setTabToolTip(existing_idx, rel)
            else:
                self.file_tabs.setTabText(existing_idx, path.name)
            self.file_tabs.setCurrentIndex(existing_idx)
            self.file_tabs.show()
            self.current_path = path
            self.snapshot = result.stdout
            self.highlighter.set_file(path.name)
            self.editor.setPlainText(result.stdout)
            from ui.icons import file_icon
            self.file_badge.setPixmap(file_icon(path).pixmap(22, 22))
            self.title_label.setText(path.name)
            self.title_label.setToolTip(rel)
            self.save_button.setEnabled(True)
            self.message_label.setText("")
        finally:
            self._switching_tab = False
        return True

    def save(self) -> bool:
        if self.current_path is None:
            return False
        try:
            rel = self._rel(self.current_path)
        except ValueError:
            return False
        result = self.controller.execute_tool(
            "write", {"path": rel, "content": self.editor.toPlainText(),
                      "_expected_sha256": hashlib.sha256(self.snapshot.encode("utf-8")).hexdigest()})
        if result.success:
            self.snapshot = self.editor.toPlainText()
            key = str(self.current_path.resolve())
            if key in self._buffers:
                self._buffers[key]["snapshot"] = self.snapshot
                self._buffers[key]["text"] = self.snapshot
                self._update_tab_label(key)
            self.message_label.setText(f"guardado: {rel}")
            return True
        self.message_label.setText(result.stderr)
        return False

    def _on_text_changed(self) -> None:
        if self._switching_tab:
            return
        if self.current_path is not None:
            key = str(self.current_path.resolve())
            if key in self._buffers:
                self._buffers[key]["text"] = self.editor.toPlainText()
                self._update_tab_label(key)
            if self.editor.toPlainText() != self.snapshot:
                self.save_button.setEnabled(True)
                self.content_changed.emit()

    def dirty(self) -> bool:
        return (self.current_path is not None
                and self.editor.toPlainText() != self.snapshot)

    def current_text(self) -> str:
        return self.editor.toPlainText()
