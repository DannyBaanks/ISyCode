"""Terminal panel: HOST SHELL only (PTY-backed on Linux/POSIX via QSocketNotifier).

This console is the human operator's shell, launched by the app on the
host. It is explicitly NOT the IsyVM sandbox and the Agent NEVER receives
access to it as a tool (core/agent/run.py does not advertise bash; the
SandboxRuntime returns UNSUPPORTED_TOOL for bash).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, QSocketNotifier, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from core.pty_shell import PtyShell, PtyShellError, is_supported as pty_is_supported

_BANNER = (
    "HOST SHELL · terminal de tu sistema, para ti. El agente no tiene acceso a esta "
    "consola: sus comandos corren en su propio sandbox aislado."
)

# Dark-theme ANSI SGR palettes (standard 30-37 and bright 90-97)
_ANSI_STANDARD_COLORS: dict[int, str] = {
    0: "#4b5563",  # black / dark gray
    1: "#f87171",  # red
    2: "#4ade80",  # green
    3: "#facc15",  # yellow
    4: "#60a5fa",  # blue
    5: "#c084fc",  # magenta
    6: "#22d3ee",  # cyan
    7: "#e5e7eb",  # white
}

_ANSI_BRIGHT_COLORS: dict[int, str] = {
    0: "#9ca3af",
    1: "#fca5a5",
    2: "#86efac",
    3: "#fde047",
    4: "#93c5fd",
    5: "#d8b4fe",
    6: "#67e8f9",
    7: "#ffffff",
}

# Matches OSC (\x1b]...BEL or ST), CSI (\x1b[...final), or 2-byte ESC sequences
_ANSI_TOKEN_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b\[[0-?]*[ -/]*[@-~]"           # CSI
    r"|\x1b[@-Z\\-_]"                     # 2-byte ESC (e.g. \x1bc reset)
)

# Matches a partial/incomplete ESC sequence at the tail of a chunk
_INCOMPLETE_ESC_RE = re.compile(
    r"\x1b(?:\][^\x07\x1b]*|\[[0-?]*[ -/]*)?$"
)

MAX_HISTORY = 500
MAX_SCROLLBACK_BLOCKS = 5000


def _xterm_256_color(index: int) -> QColor:
    """Map xterm 256-color index (0..255) to a QColor."""
    index = max(0, min(255, int(index)))
    if index < 8:
        return QColor(_ANSI_STANDARD_COLORS[index])
    if index < 16:
        return QColor(_ANSI_BRIGHT_COLORS[index - 8])
    if index < 232:
        idx = index - 16
        r = (idx // 36) % 6
        g = (idx // 6) % 6
        b = idx % 6
        levels = (0, 95, 135, 175, 215, 255)
        return QColor(levels[r], levels[g], levels[b])
    gray = 8 + (index - 232) * 10
    return QColor(gray, gray, gray)


def _apply_sgr_codes(fmt: QTextCharFormat, params: str) -> QTextCharFormat:
    """Return an updated QTextCharFormat after applying ANSI SGR parameters."""
    new_fmt = QTextCharFormat(fmt)
    if not params:
        return QTextCharFormat()
    codes: list[int] = []
    for part in params.split(";"):
        if part == "":
            codes.append(0)
        else:
            try:
                codes.append(int(part))
            except ValueError:
                continue

    i = 0
    while i < len(codes):
        code = codes[i]
        if code == 0:
            new_fmt = QTextCharFormat()
        elif code == 1:
            new_fmt.setFontWeight(QFont.Weight.Bold)
        elif code == 2:
            new_fmt.setForeground(QColor("#9aa3b2"))
        elif code == 3:
            new_fmt.setFontItalic(True)
        elif code == 4:
            new_fmt.setFontUnderline(True)
        elif code == 22:
            new_fmt.setFontWeight(QFont.Weight.Normal)
        elif code == 23:
            new_fmt.setFontItalic(False)
        elif code == 24:
            new_fmt.setFontUnderline(False)
        elif 30 <= code <= 37:
            new_fmt.setForeground(QColor(_ANSI_STANDARD_COLORS[code - 30]))
        elif code == 39:
            new_fmt.clearForeground()
        elif 40 <= code <= 47:
            new_fmt.setBackground(QColor(_ANSI_STANDARD_COLORS[code - 40]))
        elif code == 49:
            new_fmt.clearBackground()
        elif 90 <= code <= 97:
            new_fmt.setForeground(QColor(_ANSI_BRIGHT_COLORS[code - 90]))
        elif 100 <= code <= 107:
            new_fmt.setBackground(QColor(_ANSI_BRIGHT_COLORS[code - 100]))
        elif code in (38, 48) and i + 1 < len(codes):
            is_fg = code == 38
            mode = codes[i + 1]
            if mode == 5 and i + 2 < len(codes):
                color = _xterm_256_color(codes[i + 2])
                if is_fg:
                    new_fmt.setForeground(color)
                else:
                    new_fmt.setBackground(color)
                i += 2
            elif mode == 2 and i + 4 < len(codes):
                r, g, b = (max(0, min(255, c)) for c in codes[i + 2:i + 5])
                color = QColor(r, g, b)
                if is_fg:
                    new_fmt.setForeground(color)
                else:
                    new_fmt.setBackground(color)
                i += 4
        i += 1
    return new_fmt


class TerminalPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._process: QProcess | None = None
        self._pty: PtyShell | None = None
        self._notifier: QSocketNotifier | None = None
        self._ansi_buffer: str = ""
        self._ansi_format: QTextCharFormat = QTextCharFormat()
        self._history: list[str] = []
        self._history_index: int = -1
        self._history_draft: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top_row = QHBoxLayout()

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Terminal: Consola local del operador humano en el sistema operativo anfitrión.\n"
            "El agente de IA no tiene acceso a esta consola ni puede ejecutar comandos en ella."
        )
        top_row.addWidget(self.help_button)
        layout.addLayout(top_row)

        banner = QLabel(_BANNER)
        banner.setObjectName("hostShellBanner")
        banner.setWordWrap(True)
        top_row.insertWidget(0, banner, 1)

        self.cwd_label = QLabel(f"Directorio de trabajo: {self.controller.working_dir}")
        self.cwd_label.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        layout.addWidget(self.cwd_label)

        self.output = QPlainTextEdit()
        self.output.setObjectName("monoView")
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(MAX_SCROLLBACK_BLOCKS)
        self.output.installEventFilter(self)
        layout.addWidget(self.output, stretch=1)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe un comando y pulsa Enter (↑↓ historial · Ctrl+C interrumpir · Ctrl+L limpiar)…")
        self.input.returnPressed.connect(self._send)
        self.input.installEventFilter(self)
        row.addWidget(self.input, stretch=1)
        self.interrupt_button = QPushButton("Ctrl+C")
        self.interrupt_button.setToolTip("Enviar SIGINT al proceso en primer plano")
        self.interrupt_button.clicked.connect(self.send_interrupt)
        row.addWidget(self.interrupt_button)
        self.start_button = QPushButton("Iniciar shell")
        self.start_button.setProperty("variant", "primary")
        self.start_button.clicked.connect(self.start)
        row.addWidget(self.start_button)
        self.restart_button = QPushButton("Reiniciar")
        self.restart_button.setToolTip("Cierra la shell y abre una nueva en la carpeta del proyecto")
        self.restart_button.clicked.connect(self.restart)
        row.addWidget(self.restart_button)
        layout.addLayout(row)
        self._sync_shell_buttons()

    def _sync_shell_buttons(self) -> None:
        running = self.is_running()
        self.start_button.setVisible(not running)
        self.restart_button.setVisible(running)
        self.interrupt_button.setEnabled(running)

    # --- state / geometry helpers --------------------------------------

    def is_running(self) -> bool:
        if self._pty is not None and self._pty.is_running():
            return True
        if self._process is not None and self._process.state() == QProcess.ProcessState.Running:
            return True
        return False

    def _terminal_dimensions(self) -> tuple[int, int]:
        fm = self.output.fontMetrics()
        char_w = max(1, fm.horizontalAdvance("M"))
        char_h = max(1, fm.lineSpacing())
        vp = self.output.viewport()
        cols = max(40, vp.width() // char_w) if vp and vp.width() > 0 else 80
        rows = max(12, vp.height() // char_h) if vp and vp.height() > 0 else 24
        return rows, cols

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pty is not None and self._pty.is_running():
            rows, cols = self._terminal_dimensions()
            self._pty.resize(rows, cols)

    # --- lifecycle -----------------------------------------------------

    def ensure_started(self) -> None:
        self.cwd_label.setText(f"Directorio de trabajo: {self.controller.working_dir}")
        if not self.is_running():
            self.start()

    def on_workspace_changed(self) -> None:
        self.cwd_label.setText(f"Directorio de trabajo: {self.controller.working_dir}")
        if self.is_running():
            self.restart()

    def restart(self) -> None:
        self.shutdown()
        self.start()

    def shutdown(self) -> None:
        """Stop the PTY notifier/shell or fallback QProcess safely (idempotent)."""
        self._detach_notifier()
        if self._pty is not None:
            pty_shell = self._pty
            self._pty = None
            try:
                pty_shell.close(timeout=1.0)
            except Exception:
                pass
        if self._process is not None:
            proc = self._process
            self._process = None
            try:
                if proc.state() == QProcess.ProcessState.Running:
                    proc.kill()
                    proc.waitForFinished(1000)
            except RuntimeError:
                pass
        self._ansi_buffer = ""
        self._ansi_format = QTextCharFormat()

    def _detach_notifier(self) -> None:
        notifier = self._notifier
        self._notifier = None
        if notifier is not None:
            try:
                notifier.setEnabled(False)
                notifier.activated.disconnect(self._on_pty_readable)
            except (RuntimeError, TypeError):
                pass
            notifier.deleteLater()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def start(self) -> None:
        if self.is_running():
            return
        self._ansi_buffer = ""
        self._ansi_format = QTextCharFormat()
        self.cwd_label.setText(f"Directorio de trabajo: {self.controller.working_dir}")

        if pty_is_supported():
            rows, cols = self._terminal_dimensions()
            try:
                shell = PtyShell(cwd=self.controller.working_dir, rows=rows, cols=cols)
                shell.start()
            except PtyShellError:
                self._start_qprocess()
                return
            self._pty = shell
            notifier = QSocketNotifier(shell.fd, QSocketNotifier.Type.Read, self)
            notifier.activated.connect(self._on_pty_readable)
            notifier.setEnabled(True)
            self._notifier = notifier
            self._announce_start(shell._argv[0])
            return

        self._start_qprocess()

    def _start_qprocess(self) -> None:
        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(self.controller.working_dir))
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.readyReadStandardError.connect(self._read_error)
        self._process.finished.connect(
            lambda _code, _status: (self.output.appendPlainText("\n[la shell terminó]"), self._sync_shell_buttons()))
        shell = "powershell.exe" if sys.platform == "win32" else "bash"
        self._process.start(shell, ["-NoLogo"] if shell == "powershell.exe" else [])
        self._announce_start(shell)

    def _announce_start(self, shell_name: str) -> None:
        # The banner is its own block; the shell prompt must start on a fresh line.
        self.output.appendPlainText(f"── {Path(str(shell_name)).name} iniciada en {self.controller.working_dir} ──")
        self.output.appendPlainText("")
        self._sync_shell_buttons()

    # --- input, history & interrupt ------------------------------------

    def _record_history(self, command: str) -> None:
        text = command.strip()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            if len(self._history) > MAX_HISTORY:
                del self._history[:-MAX_HISTORY]
        self._history_index = -1
        self._history_draft = ""

    def history_up(self) -> None:
        if not self._history:
            return
        if self._history_index == -1:
            self._history_draft = self.input.text()
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        self.input.setText(self._history[self._history_index])
        self.input.end(False)

    def history_down(self) -> None:
        if self._history_index == -1:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.input.setText(self._history[self._history_index])
        else:
            self._history_index = -1
            self.input.setText(self._history_draft)
        self.input.end(False)

    def clear_output(self) -> None:
        self.output.clear()

    def send_interrupt(self) -> bool:
        """Deliver SIGINT (Ctrl+C) to the foreground process group."""
        if self._pty is not None and self._pty.is_running():
            ok = self._pty.send_interrupt()
            if not ok:
                self._pty.write(b"\x03")
            return ok
        if self._process is not None and self._process.state() == QProcess.ProcessState.Running:
            self._process.write(b"\x03")
            return True
        return False

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            if obj is self.input:
                if key == Qt.Key.Key_Up:
                    self.history_up()
                    return True
                if key == Qt.Key.Key_Down:
                    self.history_down()
                    return True
                if key == Qt.Key.Key_C and (mods & Qt.KeyboardModifier.ControlModifier) and not self.input.hasSelectedText():
                    self.send_interrupt()
                    return True
                if key == Qt.Key.Key_L and (mods & Qt.KeyboardModifier.ControlModifier):
                    self.clear_output()
                    return True
            elif obj is self.output:
                if key == Qt.Key.Key_C and (mods & Qt.KeyboardModifier.ControlModifier) and not self.output.textCursor().hasSelection():
                    self.send_interrupt()
                    return True
                if key == Qt.Key.Key_L and (mods & Qt.KeyboardModifier.ControlModifier):
                    self.clear_output()
                    return True
        return super().eventFilter(obj, event)

    def _send(self) -> None:
        if not self.is_running():
            self.output.appendPlainText("La shell no está activa; pulsa «Iniciar shell».")
            return
        command = self.input.text()
        self.input.clear()
        self._record_history(command)
        if self._pty is not None and self._pty.is_running():
            self._pty.writeline(command)
            return
        if self._process is not None and self._process.state() == QProcess.ProcessState.Running:
            self.output.appendPlainText(f"> {command}")
            self._process.write((command + "\n").encode("utf-8"))

    # --- PTY & QProcess output + ANSI SGR rendering --------------------

    def _on_pty_readable(self, _fd: int = 0) -> None:
        if self._pty is None:
            return
        data = self._pty.read_text()
        if data:
            self.append_ansi(data)
        elif data is None:
            # Flush any trailing buffered text before closing
            if self._ansi_buffer:
                leftover = self._ansi_buffer
                self._ansi_buffer = ""
                self._insert_plain(leftover)
            self._detach_notifier()
            pty_shell = self._pty
            self._pty = None
            try:
                pty_shell.close(timeout=0.2)
            except Exception:
                pass
            self.output.appendPlainText("\n[la shell terminó]")
            self._sync_shell_buttons()

    def append_ansi(self, text: str) -> None:
        """Parse ANSI SGR colors, clear-screen, OSC, CR/BS and render into output."""
        if not text:
            return
        combined = self._ansi_buffer + text
        self._ansi_buffer = ""

        # Hold back any incomplete ESC sequence at the tail for the next read chunk
        tail = _INCOMPLETE_ESC_RE.search(combined)
        if tail is not None:
            self._ansi_buffer = combined[tail.start():]
            combined = combined[:tail.start()]

        pos = 0
        for match in _ANSI_TOKEN_RE.finditer(combined):
            if match.start() > pos:
                self._insert_plain(combined[pos:match.start()])
            seq = match.group(0)
            self._handle_escape_sequence(seq)
            pos = match.end()
        if pos < len(combined):
            self._insert_plain(combined[pos:])

        bar = self.output.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _handle_escape_sequence(self, seq: str) -> None:
        if seq == "\x1bc":
            self.output.clear()
            self._ansi_format = QTextCharFormat()
            return
        if seq.startswith("\x1b]"):
            # OSC (e.g. window title) — ignore cleanly
            return
        if seq.startswith("\x1b["):
            final = seq[-1]
            params = seq[2:-1]
            if final == "m":
                self._ansi_format = _apply_sgr_codes(self._ansi_format, params)
            elif final == "J" and params in ("2", "3"):
                self.output.clear()
            elif final == "K" and params in ("", "0", "2"):
                # Erase to end of line / whole line
                if params == "2":
                    cursor = self.output.textCursor()
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                    cursor.removeSelectedText()

    def _insert_plain(self, segment: str) -> None:
        if not segment:
            return
        # Normalize CRLF to LF, strip BEL (\x07)
        segment = segment.replace("\r\n", "\n").replace("\x07", "")
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        buf: list[str] = []

        def flush():
            if buf:
                cursor.insertText("".join(buf), self._ansi_format)
                buf.clear()

        for ch in segment:
            if ch == "\x08":  # Backspace
                flush()
                if cursor.positionInBlock() > 0:
                    cursor.deletePreviousChar()
            elif ch == "\r":  # Carriage return without LF -> overwrite current line
                flush()
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
            else:
                buf.append(ch)
        flush()
        self.output.setTextCursor(cursor)

    def _read_output(self) -> None:
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        self.append_ansi(data)

    def _read_error(self) -> None:
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardError()).decode("utf-8", "replace")
        self.append_ansi(data)
