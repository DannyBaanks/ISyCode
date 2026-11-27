"""Terminal panel: HOST SHELL only.

This console is the human operator's shell, launched by the app on the
host. It is explicitly NOT the IsyVM sandbox and the Agent NEVER receives
access to it as a tool (core/agent/run.py does not advertise bash; the
SandboxRuntime returns UNSUPPORTED_TOOL for bash).
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

_BANNER = (
    "HOST SHELL — consola del OPERADOR HUMANO, no del agente.\n"
    "No es el sandbox de IsyVM (Layer_a best-effort). El agente no tiene "
    "acceso a esta consola."
)


class TerminalPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._process: QProcess | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_lbl = QLabel("HOST SHELL — TERMINAL DEL SISTEMA")
        top_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #6b7385; letter-spacing: 1px;")
        top_row.addWidget(top_lbl)
        top_row.addStretch(1)

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
        layout.addWidget(banner)

        self.cwd_label = QLabel(f"Directorio de trabajo: {self.controller.working_dir}")
        self.cwd_label.setStyleSheet("color: #9aa3b2; font-size: 11px;")
        layout.addWidget(self.cwd_label)

        self.output = QPlainTextEdit()
        self.output.setObjectName("monoView")
        self.output.setReadOnly(True)
        layout.addWidget(self.output, stretch=1)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe un comando y pulsa Enter (host shell)…")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, stretch=1)
        self.start_button = QPushButton("Start shell")
        self.start_button.setProperty("variant", "primary")
        self.start_button.clicked.connect(self.start)
        row.addWidget(self.start_button)
        self.restart_button = QPushButton("Reiniciar en proyecto")
        self.restart_button.clicked.connect(self.restart)
        row.addWidget(self.restart_button)
        layout.addLayout(row)

    def ensure_started(self) -> None:
        self.cwd_label.setText(f"Directorio de trabajo: {self.controller.working_dir}")
        if self._process is None or self._process.state() != QProcess.ProcessState.Running:
            self.start()

    def on_workspace_changed(self) -> None:
        self.cwd_label.setText(f"Directorio de trabajo: {self.controller.working_dir}")
        if self._process is not None and self._process.state() == QProcess.ProcessState.Running:
            self.restart()

    def restart(self) -> None:
        if self._process is not None and self._process.state() == QProcess.ProcessState.Running:
            self._process.kill()
            self._process.waitForFinished(1000)
        self.start()

    def start(self) -> None:
        if self._process is not None and self._process.state() == QProcess.ProcessState.Running:
            return
        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(self.controller.working_dir))
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.readyReadStandardError.connect(self._read_error)
        self._process.finished.connect(
            lambda _code, _status: self.output.appendPlainText("\n[host shell exited]"))
        shell = "powershell.exe" if sys.platform == "win32" else "bash"
        self._process.start(shell, ["-NoLogo"] if shell == "powershell.exe" else [])
        self.output.appendPlainText(f"$ {shell} started in {self.controller.working_dir}")

    def _send(self) -> None:
        if self._process is None or self._process.state() != QProcess.ProcessState.Running:
            self.output.appendPlainText("shell not running; press Start shell")
            return
        command = self.input.text()
        self.input.clear()
        self.output.appendPlainText(f"> {command}")
        self._process.write((command + "\n").encode("utf-8"))

    def _read_output(self) -> None:
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        self.output.appendPlainText(data.rstrip())

    def _read_error(self) -> None:
        data = bytes(self._process.readAllStandardError()).decode("utf-8", "replace")
        self.output.appendPlainText(data.rstrip())