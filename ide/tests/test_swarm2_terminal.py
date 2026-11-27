"""Tests for POSIX PtyShell, PTY-backed TerminalPanel (ANSI/Ctrl+C/history/shutdown) & P0-1 closeEvent."""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QColor, QFont, QKeyEvent
from PySide6.QtWidgets import QLabel

from core.pty_shell import PtyShell, is_supported as pty_is_supported
from ui.app import AppController
from ui.main_window import MainWindow
from ui.panels.terminal import TerminalPanel


def _read_until(shell: PtyShell, needle: str, timeout: float = 3.0) -> str:
    buf = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = shell.read_text()
        if chunk:
            buf += chunk
            if needle in buf:
                return buf
        elif chunk is None:
            break
        else:
            time.sleep(0.02)
    return buf


# ---------------------------------------------------------------------------
# 1. core/pty_shell.py — real POSIX PTY lifecycle, resize, SIGINT, clean close
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not pty_is_supported(), reason="POSIX PTY required")
def test_pty_shell_tty_resize_interrupt_and_close(tmp_path: Path):
    shell = PtyShell(argv=["/bin/bash", "--norc", "--noprofile"], cwd=tmp_path, rows=30, cols=100)
    shell.start()
    try:
        assert shell.is_running()
        assert shell.fd is not None and shell.pid is not None

        shell.writeline("tty; stty size; printf 'READY_%s\\n' MARKER")
        out = _read_until(shell, "READY_MARKER")
        assert "/dev/pts/" in out
        assert "30 100" in out

        # Resize propagates TIOCSWINSZ
        shell.resize(42, 120)
        shell.writeline("stty size; printf 'RESIZED_%s\\n' OK")
        out2 = _read_until(shell, "RESIZED_OK")
        assert "42 120" in out2

        # Foreground sleep is interrupted by send_interrupt (SIGINT)
        shell.writeline("sleep 30; echo AFTER_SLEEP")
        time.sleep(0.15)
        assert shell.send_interrupt() is True
        shell.writeline("printf 'INTERRUPTED_%s\\n' OK")
        out3 = _read_until(shell, "INTERRUPTED_OK")
        assert "INTERRUPTED_OK" in out3
    finally:
        shell.close(timeout=1.0)
    assert not shell.is_running()
    assert shell.fd is None


# ---------------------------------------------------------------------------
# 2. ui/panels/terminal.py — ANSI SGR colors, clear screen, split escapes, history
# ---------------------------------------------------------------------------

def test_terminal_panel_ansi_sgr_clear_and_split_escape(qtbot, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    controller = AppController(tmp_path)
    panel = TerminalPanel(controller)
    qtbot.addWidget(panel)

    # Preserves legacy banner & attributes
    banner = panel.findChild(QLabel)
    assert banner is not None and "HOST SHELL" in banner.text()
    for attr in ("output", "input", "start_button", "restart_button", "help_button", "cwd_label"):
        assert hasattr(panel, attr)

    # SGR bold red + OSC title stripping + split escape across two chunks
    panel.append_ansi("\x1b]0;Window Title\x07normal \x1b[1;31mRED\x1b[0m \x1b[38;5;46")
    panel.append_ansi("mGREEN\x1b[0m")
    plain = panel.output.toPlainText()
    assert "Window Title" not in plain
    assert plain == "normal RED GREEN"

    # Verify QTextCharFormat actually carries bold + red foreground on "RED"
    doc = panel.output.document()
    block = doc.begin()
    formats = []
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        if frag.isValid():
            formats.append((frag.text(), frag.charFormat()))
        it += 1
    red_fmt = next(fmt for text, fmt in formats if text == "RED")
    assert red_fmt.fontWeight() == QFont.Weight.Bold
    assert red_fmt.foreground().color() == QColor("#f87171")

    # Clear-screen escape clears the document
    panel.append_ansi("\x1b[2Jfresh")
    assert panel.output.toPlainText() == "fresh"

    panel.shutdown()


def test_terminal_panel_history_up_down_and_ctrl_l(qtbot, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    controller = AppController(tmp_path)
    panel = TerminalPanel(controller)
    qtbot.addWidget(panel)

    panel._record_history("echo one")
    panel._record_history("echo two")
    panel.input.setText("draft")

    panel.history_up()
    assert panel.input.text() == "echo two"
    panel.history_up()
    assert panel.input.text() == "echo one"
    panel.history_down()
    assert panel.input.text() == "echo two"
    panel.history_down()
    assert panel.input.text() == "draft"

    # Ctrl+L via eventFilter clears output
    panel.output.setPlainText("stale output")
    ctrl_l = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    assert panel.eventFilter(panel.input, ctrl_l) is True
    assert panel.output.toPlainText() == ""

    panel.shutdown()


@pytest.mark.skipif(not pty_is_supported(), reason="POSIX PTY required")
def test_terminal_panel_live_pty_qsocketnotifier_and_shutdown(qtbot, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    controller = AppController(tmp_path)
    panel = TerminalPanel(controller)
    qtbot.addWidget(panel)

    panel.ensure_started()
    assert panel.is_running()
    assert panel._pty is not None
    assert panel._notifier is not None

    panel.input.setText("printf 'PTY_PANEL_%s\\n' OK")
    panel._send()
    qtbot.waitUntil(lambda: "PTY_PANEL_OK" in panel.output.toPlainText(), timeout=4000)

    # Ctrl+C sends SIGINT to live PTY
    assert panel.send_interrupt() is True

    # Shutdown cleanly disables notifier and terminates PTY
    panel.shutdown()
    assert not panel.is_running()
    assert panel._pty is None
    assert panel._notifier is None


# ---------------------------------------------------------------------------
# 3. ui/main_window.py — P0-1 closeEvent bounded wait + terminal shutdown
# ---------------------------------------------------------------------------

def test_main_window_close_event_shuts_down_terminal_and_waits_for_worker(qtbot, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    controller = AppController(tmp_path)
    win = MainWindow(controller=controller)
    qtbot.addWidget(win)

    shutdown_called = []
    orig_shutdown = win.terminal_panel.shutdown
    win.terminal_panel.shutdown = lambda: (shutdown_called.append(True), orig_shutdown())

    # Attach a real QThread that stops promptly when cancelled
    class _CancellableWorker(QThread):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

        def run(self):
            deadline = time.monotonic() + 5.0
            while not self.cancelled and time.monotonic() < deadline:
                time.sleep(0.01)

    worker = _CancellableWorker(parent=win)
    win._worker = worker
    win.show()
    worker.start()
    qtbot.waitUntil(worker.isRunning, timeout=2000)

    win.close()
    assert shutdown_called == [True]
    assert worker.cancelled is True
    assert not worker.isRunning()
