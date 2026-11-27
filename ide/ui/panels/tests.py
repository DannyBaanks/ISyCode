"""Explicit project test commands through common isolated host authority."""

from __future__ import annotations

from datetime import datetime
import uuid

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)
from core.runtime.base import ToolCall
from ..thread import HostToolWorker
from ..approval_dialog import request_decision
from ..widgets import format_command, mono_font, parse_command


def discover_project_tests(working_dir) -> dict:
    """Detect test framework and candidate test files without running code."""
    from pathlib import Path
    root = Path(working_dir)
    if not root.is_dir():
        return {"framework": "none", "count": 0, "argv": ["python3", "-m", "pytest", "-q"], "detail": "Carpeta no disponible."}
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "target"}
    py_tests = []
    for sub in (root / "tests", root / "test", root):
        if not sub.is_dir():
            continue
        try:
            for item in sub.iterdir():
                if item.name in skip:
                    continue
                if item.is_file() and (item.name.startswith("test_") or item.name.endswith("_test.py")) and item.suffix == ".py":
                    py_tests.append(item.name)
        except OSError:
            continue
        if py_tests and sub != root:
            break
    if py_tests:
        has_pytest = (root / "pytest.ini").exists() or (root / "pyproject.toml").exists() or (root / "conftest.py").exists() or (root / "tests" / "conftest.py").exists()
        if has_pytest:
            return {"framework": "pytest", "count": len(py_tests), "argv": ["python3", "-m", "pytest", "-q"],
                    "detail": f"pytest detectado · {len(py_tests)} archivo(s) de prueba ({', '.join(sorted(py_tests)[:4])})"}
        return {"framework": "unittest", "count": len(py_tests), "argv": ["python3", "-B", "-m", "unittest", "discover", "-v"],
                "detail": f"unittest detectado · {len(py_tests)} archivo(s) de prueba ({', '.join(sorted(py_tests)[:4])})"}
    if (root / "build.zig").is_file():
        return {"framework": "zig", "count": 1, "argv": ["zig", "build", "test"],
                "detail": "Proyecto Zig detectado (build.zig) · comando sugerido: zig build test"}
    if (root / "Cargo.toml").is_file():
        return {"framework": "cargo", "count": 1, "argv": ["cargo", "test"],
                "detail": "Proyecto Rust detectado (Cargo.toml) · comando sugerido: cargo test"}
    if (root / "package.json").is_file():
        return {"framework": "npm", "count": 1, "argv": ["npm", "test"],
                "detail": "Proyecto Node detectado (package.json) · comando sugerido: npm test"}
    return {"framework": "none", "count": 0, "argv": ["python3", "-m", "pytest", "-q"],
            "detail": "No se detectaron archivos de prueba en este proyecto. Puedes pedir al agente en CODER que cree el primer test o introducir un comando argv manualmente."}


class TestsPanel(QWidget):
    result_ready = Signal(object)
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._worker = None
        self.busy_guard = lambda: False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        row = QHBoxLayout()
        self.discovery_label = QLabel("")
        self.discovery_label.setWordWrap(True)
        self.discovery_label.setStyleSheet("color: #adbed1; font-size: 13px;")
        row.addWidget(self.discovery_label, 1)

        self.run_button = QPushButton("Revisar y ejecutar")
        self.run_button.setProperty("variant", "primary")
        self.run_button.setToolTip("Ejecuta la suite de pruebas del proyecto en copia aislada")
        self.run_button.clicked.connect(self.run)

        self.discover_button = QPushButton("Detectar pruebas")
        self.discover_button.clicked.connect(self.refresh_discovery)
        row.addWidget(self.discover_button)

        self.stop_button = QPushButton("Detener")
        self.stop_button.setProperty("variant", "danger")
        self.stop_button.setEnabled(False)
        self.stop_button.setVisible(False)
        self.stop_button.clicked.connect(self.cancel)
        row.addWidget(self.stop_button)
        row.addWidget(self.run_button)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Tests: Descubre y ejecuta la suite de pruebas del proyecto en copia aislada,\n"
            "mostrando la salida estándar, error, exit code y fecha de la última ejecución."
        )
        row.addWidget(self.help_button)
        layout.addLayout(row)

        cmd_row = QHBoxLayout()
        cmd_label = QLabel("Comando")
        cmd_label.setStyleSheet("color: #adbed1; font-weight: 600;")
        cmd_row.addWidget(cmd_label)
        self.command = QLineEdit("python3 -m pytest -q")
        self.command.setFont(mono_font(11))
        self.command.setPlaceholderText("por ejemplo: python3 -m unittest discover -v")
        self.command.returnPressed.connect(self.run)
        cmd_row.addWidget(self.command, 1)
        layout.addLayout(cmd_row)
        hint = QLabel("Se ejecuta en una copia aislada con las herramientas del sistema (sin venv, node_modules ni credenciales).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #859ab2; font-size: 12px;")
        layout.addWidget(hint)
        self.last_run_label = QLabel("Última ejecución: ninguna en esta sesión")
        self.last_run_label.setStyleSheet("color: #859ab2; font-size: 12px;")
        layout.addWidget(self.last_run_label)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(mono_font(11))
        layout.addWidget(self.output, stretch=1)
        self.refresh_discovery()

    def refresh_discovery(self) -> None:
        info = discover_project_tests(self.controller.working_dir)
        self.discovery_label.setText(f"{self.controller.working_dir.name}: {info['detail']}")
        if info["framework"] != "none":
            self.command.setText(format_command(info["argv"]))
        self.output.setPlaceholderText(
            f"Proyecto: {self.controller.working_dir}\n"
            f"Detección: {info['detail']}\n"
            f"Comando listo: {self.command.text()}\n\n"
            "Pulsa «Revisar y ejecutar» para correr la suite en copia aislada."
        )

    def run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if self.busy_guard():
            self.output.appendPlainText("Espera a que termine el agente o la operación Git antes de ejecutar pruebas.")
            return
        try:
            argv = parse_command(self.command.text())
            if not argv:
                raise ValueError()
        except ValueError:
            self.output.appendPlainText("Introduce un comando, por ejemplo: python3 -m pytest -q")
            return
        self.output.clear()
        self.run_button.setEnabled(False)
        service, mode = self.controller.tool_execution, self.controller.mode()
        async def operation(approve):
            return await service.execute(ToolCall("run_command", {"argv": argv, "timeout": 120}, uuid.uuid4().hex),
                                         mode=mode, actor="HOST", approve=approve)
        worker = HostToolWorker(operation, parent=self)
        self._worker = worker
        worker.approval_requested.connect(self._approve)
        worker.ready.connect(self._result)
        worker.failed.connect(self.output.appendPlainText)
        worker.finished.connect(lambda w=worker: self._finished(w))
        self.stop_button.setEnabled(True)
        self.stop_button.setVisible(True)
        worker.start()

    def _approve(self, identifier, tool_name, arguments, diff):
        worker = self._worker
        if worker is not None and worker.isRunning():
            answer = request_decision(self, tool_name, arguments, diff)
            worker.resolve_approval(identifier, answer)

    def _result(self, result):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_run_label.setText(f"Última ejecución: {stamp} · exit {result.returncode} · {result.error_code or 'OK'}")
        self.output.appendPlainText(result.stdout)
        self.output.appendPlainText(result.stderr)
        self.output.appendPlainText(f"\nResultado ({stamp}): exit {result.returncode} · {result.error_code or 'sin error del host'}")
        self.output.appendPlainText("Consulta la salida y el número de pruebas descubiertas; exit 0 por sí solo no demuestra corrección.")
        self.result_ready.emit(result)

    def cancel(self):
        if self._worker is not None:
            self._worker.cancel()
        self.output.appendPlainText("Cancelación solicitada.")

    def _finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.stop_button.setVisible(False)
        worker.deleteLater()
