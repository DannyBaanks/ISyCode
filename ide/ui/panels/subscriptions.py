"""Explicit private subscription setup. No automatic account/token import."""
from __future__ import annotations

import asyncio
import shutil
from PySide6.QtCore import QThread, Signal, QUrl, Qt, QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from core.subscriptions import SubscriptionService, KINDS, ENDPOINTS
from ui.icons import provider_icon


class AccountJob(QThread):
    ready = Signal(object)
    failed = Signal(str)
    challenge = Signal(object)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.loop = self.task = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.loop and self.task:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass

    def run(self):
        async def run():
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.current_task()
            if self.cancelled:
                return
            try:
                self.ready.emit(await self.operation(self.challenge.emit))
            except asyncio.CancelledError:
                self.failed.emit("Operación cancelada; el conector conserva su estado de autenticación.")
            except Exception:
                self.failed.emit("No se pudo comprobar el conector. Revisa el CLI seleccionado, su versión y el acceso en el navegador.")
        try:
            asyncio.run(run())
        finally:
            self.loop = self.task = None


class SubscriptionPanel(QWidget):
    providers_changed = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.service = SubscriptionService()
        self._worker = None
        self._kind = "codex-subscription"
        self._challenge_url = None
        self.busy_guard = lambda: False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        heading = QLabel("Cuentas de suscripción")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        intro = QLabel("Usa el CLI oficial con un perfil propio del IDE. Elige su ejecutable y pulsa Preparar antes de iniciar sesión. Los modelos siguen solicitando permisos al host.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.kind = QComboBox()
        self.kind.setIconSize(QSize(22, 22))
        for kind, label in [("codex-subscription", "ChatGPT · Codex oficial"), ("claude-subscription", "Claude · CLI oficial restringido"), ("grok-subscription", "Grok · sesión del CLI oficial")]:
            self.kind.addItem(provider_icon(config={"provider": kind}), label, kind)
        form.addRow("Cuenta", self.kind)
        self.executable = QLineEdit()
        self.executable.setPlaceholderText("Ruta del CLI oficial instalado")
        form.addRow("Ejecutable", self.executable)
        browse = QPushButton("Elegir ejecutable…")
        browse.clicked.connect(self._browse)
        form.addRow("", browse)
        self.name = QLineEdit("chatgpt")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setCurrentText("auto")
        form.addRow("Nombre de conexión", self.name)
        form.addRow("Modelo", self.model)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.prepare = QPushButton("Preparar conector")
        self.inspect = QPushButton("Comprobar sesión")
        self.login = QPushButton("Iniciar sesión oficial")
        self.logout = QPushButton("Cerrar sesión del IDE")
        for button, callback in [(self.prepare, self._prepare), (self.inspect, lambda: self._start(False)), (self.login, lambda: self._start(True))]:
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.logout.clicked.connect(lambda: self._start("logout"))
        layout.addWidget(self.logout)
        self.cancel = QPushButton("Cancelar acceso/consulta")
        self.cancel.clicked.connect(lambda: self._worker.cancel() if self._worker else None)
        self.cancel.hide()
        layout.addWidget(self.cancel)
        self.status = QLabel("Sin comprobar. Preparar no autentica una cuenta.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.challenge = QPushButton("Abrir acceso oficial en navegador")
        self.challenge.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._challenge_url)) if self._challenge_url else None)
        self.challenge.hide()
        layout.addWidget(self.challenge)
        self.save = QPushButton("Guardar conexión de suscripción")
        self.save.setProperty("variant", "primary")
        self.save.clicked.connect(self._save)
        layout.addWidget(self.save)
        note = QLabel("ChatGPT usa app-server y herramientas dinámicas; Claude devuelve propuestas estructuradas con herramientas nativas apagadas. Grok usa el transporte de sesión del adaptador TUI: su compatibilidad real requiere comprobación. Las claves API son conexiones independientes. No se modifica la configuración global de Codex, Claude o Grok.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.kind.currentIndexChanged.connect(self._select)
        self._select()

    def _select(self):
        self._kind = self.kind.currentData()
        executable = shutil.which(KINDS[self._kind]) or ""
        try:
            executable = self.service.identity(self._kind)["executable"]
        except (ValueError, OSError):
            pass
        self.executable.setText(executable)
        self.name.setText({"codex-subscription": "chatgpt", "claude-subscription": "claude-session", "grok-subscription": "grok-session"}[self._kind])
        self.model.clear()
        self.model.setCurrentText({"codex-subscription": "auto", "claude-subscription": "sonnet", "grok-subscription": ""}[self._kind])
        self.status.setText("Sin comprobar. El modelo se confirmará con el conector; puedes introducir su ID.")
        self.challenge.hide()
        self._challenge_url = None

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir CLI oficial")
        if path:
            self.executable.setText(path)

    def _prepare(self):
        if self.busy_guard():
            self.status.setText("Espera a que termine el turno antes de cambiar el conector.")
            return
        try:
            identity = self.service.configure(self._kind, self.executable.text())
            self.status.setText("Conector preparado · ejecutable identificado por SHA-256. Perfil: " + identity["home"] + ". Comprueba o inicia sesión.")
        except (ValueError, OSError):
            self.status.setText("No se pudo preparar el conector. Selecciona un ejecutable oficial instalado.")

    def _start(self, login):
        if self._worker is not None:
            return
        if self.busy_guard():
            self.status.setText("Espera a que termine el turno antes de acceder a la cuenta.")
            return
        kind = self._kind
        async def operation(callback):
            if login == "logout":
                return await self.service.logout(kind)
            return await self.service.login(kind, callback) if login else await self.service.inspect(kind)
        worker = AccountJob(operation, self)
        self._worker = worker
        worker.ready.connect(self._ready)
        worker.failed.connect(self.status.setText)
        worker.challenge.connect(self._challenge)
        worker.finished.connect(lambda w=worker: self._finished(w))
        self.status.setText("Iniciando acceso…" if login else "Comprobando sesión privada…")
        for widget in (self.kind, self.executable, self.prepare, self.inspect, self.login, self.logout, self.save):
            widget.setEnabled(False)
        self.cancel.show()
        worker.start()

    def _challenge(self, value):
        self._challenge_url = value.get("url")
        self.challenge.setVisible(bool(self._challenge_url))
        self.status.setText(value.get("message", "Abre el acceso oficial y completa la autenticación. Esta ventana esperará su resultado."))

    def _ready(self, report):
        if report["state"] == "stored_session_unverified":
            self.status.setText("Sesión Grok guardada con fecha válida; el servicio todavía no se ha comprobado. Introduce el ID del modelo y revisa el resultado del primer turno.")
            return
        self.status.setText("Sesión autenticada; generación todavía sin comprobar." if report["authenticated"] else "Sesión ausente o expirada. Inicia el acceso oficial.")
        if report["models"]:
            previous = self.model.currentText()
            self.model.clear()
            self.model.addItems(report["models"])
            if previous in report["models"]:
                self.model.setCurrentText(previous)

    def _finished(self, worker):
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()
        self.cancel.hide()
        self.challenge.hide()
        self._challenge_url = None
        for widget in (self.kind, self.executable, self.prepare, self.inspect, self.login, self.logout, self.save):
            widget.setEnabled(True)

    def _save(self):
        try:
            self.service.identity(self._kind)
            name = self.name.text().strip()
            existing = self.controller.providers().get(name)
            if existing and existing.get("provider") != self._kind:
                self.status.setText("Ese nombre pertenece a otra conexión. Elige un nombre distinto.")
                return
            self.controller.add_provider(name, self._kind, self.model.currentText().strip(), auth="subscription", endpoint=ENDPOINTS[self._kind], timeout=180)
            self.providers_changed.emit()
            self.status.setText("Conexión guardada. Selecciónala en la barra; guardar no demuestra una generación correcta.")
        except (ValueError, OSError):
            self.status.setText("Prepara el conector e introduce nombre y modelo válidos antes de guardar.")
