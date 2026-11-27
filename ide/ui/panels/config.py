"""Provider workspace: catalog, editable profiles and asynchronous model discovery."""

from __future__ import annotations

import asyncio

from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from core.agent.providers.base import ProviderConfig
from core.agent.providers.registry import validate_config
from core.provider_service import ConnectionReport
from ui.icons import provider_icon


class _InspectWorker(QThread):
    report_ready = Signal(object)

    def __init__(self, service, config, key):
        super().__init__()
        self.service, self.config, self.key = service, config, key
        self.loop = None
        self.task = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.loop is not None and self.task is not None:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass

    def run(self):
        async def inspect():
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.current_task()
            if self.cancelled:
                return
            try:
                report = await self.service.inspect_config(self.config, self.key)
            except asyncio.CancelledError:
                report = ConnectionReport(self.config.name, "cancelled", "Consulta cancelada.")
            except Exception:
                report = ConnectionReport(self.config.name, "error", "No se pudo consultar el catálogo.")
            self.report_ready.emit(report)
        try:
            asyncio.run(inspect())
        finally:
            self.key = None
            self.loop = self.task = None


# Keep running threads alive if the floating providers window closes.
_INSPECTIONS = set()


class ConfigPanel(QWidget):
    providers_changed = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.service = controller.provider_service
        self._worker = None
        self._editing = False
        self._draft_revision = 0
        self._probe_revision = 0
        self._last_checks: dict[str, str] = {}
        self.setObjectName("providerWorkspace")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)
        api_page = QWidget()
        self.tabs.addTab(api_page, "API y modelos locales")
        from .subscriptions import SubscriptionPanel
        self.subscriptions = SubscriptionPanel(controller, self)
        self.subscriptions.providers_changed.connect(self.providers_changed.emit)
        self.subscriptions.providers_changed.connect(self.refresh)
        self.tabs.addTab(self.subscriptions, "Suscripciones")
        layout = QVBoxLayout(api_page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        title = QLabel("Proveedores y modelos")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(title)
        subtitle = QLabel("Configura una API o un modelo local para empezar a conversar.")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["Todos", "API", "Local"])
        self.filter_combo.currentTextChanged.connect(self._filter_catalog)
        ll.addWidget(self.filter_combo)
        ll.addWidget(QLabel("CATÁLOGO"))
        self.catalog_list = QListWidget()
        self.catalog_list.setMinimumWidth(185)
        self.catalog_list.setIconSize(QSize(24, 24))
        for preset in self.service.catalog():
            item = QListWidgetItem(provider_icon(preset.id, size=24), preset.label + "  ·  " + preset.category)
            item.setSizeHint(QSize(0, 36))
            item.setData(Qt.ItemDataRole.UserRole, preset.id)
            self.catalog_list.addItem(item)
        self.catalog_list.currentItemChanged.connect(self._select_preset)
        ll.addWidget(self.catalog_list, 2)
        ll.addWidget(QLabel("MIS CONEXIONES"))
        self.profiles = QListWidget()
        self.profiles.setIconSize(QSize(24, 24))
        self.profiles.currentItemChanged.connect(self._select_profile)
        ll.addWidget(self.profiles, 1)
        self.refresh_button = QPushButton("Actualizar conexiones")
        self.refresh_button.clicked.connect(self.refresh)
        ll.addWidget(self.refresh_button)
        split.addWidget(left)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        right = QWidget()
        form_box = QVBoxLayout(right)
        form_box.setContentsMargins(20, 0, 4, 0)
        form_box.setSpacing(14)
        self.profile_title = QLabel("Nueva conexión")
        self.profile_title.setStyleSheet("font-size: 19px; font-weight: 600;")
        heading = QHBoxLayout()
        self.profile_logo = QLabel()
        self.profile_logo.setFixedSize(30, 30)
        heading.addWidget(self.profile_logo)
        heading.addWidget(self.profile_title, 1)
        form_box.addLayout(heading)
        self.profile_hint = QLabel("Elige un provider del catálogo o edita una conexión guardada.")
        self.profile_hint.setWordWrap(True)
        form_box.addWidget(self.profile_hint)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(12)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("ej. mi-openai")
        self.type_combo = QComboBox()
        self.type_combo.addItems([kind for kind in controller.provider_types() if kind != "claude" and not kind.endswith("-subscription")])
        self.type_combo.currentTextChanged.connect(self._on_provider_type_changed)
        self.endpoint_input = QLineEdit()
        self.endpoint_input.setPlaceholderText("https://servidor/v1")
        self.auth_combo = QComboBox()
        self.auth_combo.addItem("Clave API", "api_key")
        self.auth_combo.addItem("Sin autenticación (local/compatible)", "none")
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Introduce una clave o conserva la ya guardada")
        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model_input.lineEdit().setPlaceholderText("Consulta modelos o escribe el ID")
        form.addRow("Nombre", self.name_input)
        form.addRow("Protocolo", self.type_combo)
        form.addRow("Endpoint", self.endpoint_input)
        form.addRow("Autenticación", self.auth_combo)
        form.addRow("Clave API", self.key_input)
        form.addRow("Modelo", self.model_input)
        form_box.addLayout(form)

        query_row = QHBoxLayout()
        self.inspect_button = QPushButton("Consultar modelos")
        self.inspect_button.clicked.connect(self.inspect_models)
        self.cancel_button = QPushButton("Cancelar consulta")
        self.cancel_button.clicked.connect(self._cancel_inspection)
        self.cancel_button.setVisible(False)
        query_row.addWidget(self.inspect_button)
        query_row.addWidget(self.cancel_button)
        query_row.addStretch()
        form_box.addLayout(query_row)
        self.connection_status = QLabel("Sin comprobar. Guardar una conexión no verifica su funcionamiento.")
        self.connection_status.setWordWrap(True)
        self.connection_status.setTextFormat(Qt.TextFormat.PlainText)
        self.connection_status.setObjectName("providerConnectionStatus")
        form_box.addWidget(self.connection_status)
        self.storage_label = QLabel("")
        self.storage_label.setWordWrap(True)
        self.storage_label.setObjectName("providerStorageStatus")
        self._show_keyring_banner()
        form_box.addWidget(self.storage_label)
        actions = QHBoxLayout()
        self.add_button = QPushButton("Guardar conexión")
        self.add_button.setProperty("variant", "primary")
        self.add_button.clicked.connect(self.add_provider)
        self.remove_button = QPushButton("Eliminar conexión")
        self.remove_button.setProperty("variant", "danger")
        self.remove_button.clicked.connect(self.remove_provider)
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        form_box.addLayout(actions)
        form_box.addStretch()
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        form_box.addWidget(separator)
        note = QLabel("Para ChatGPT, Claude o Grok por suscripción, abre la pestaña Suscripciones. Las claves API se configuran aquí.")
        note.setWordWrap(True)
        form_box.addWidget(note)
        self.import_button = QPushButton("Importar claves API desde auth.json…")
        self.import_button.clicked.connect(self.import_opencode)
        form_box.addWidget(self.import_button)
        self.help_button = QPushButton("Ayuda de conexión")
        self.help_button.clicked.connect(lambda: QMessageBox.information(
            self, "Providers", "1. Elige un provider.\n2. Introduce endpoint y autenticación.\n3. Consulta modelos o escribe el ID.\n4. Guarda la conexión y selecciónala en la barra superior.\n\nConsultar modelos no envía un prompt ni verifica compatibilidad con herramientas."
        ))
        form_box.addWidget(self.help_button)
        scroll.setWidget(right)
        split.addWidget(scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 650])
        layout.addWidget(split, 1)
        for widget in (self.name_input, self.endpoint_input, self.key_input):
            widget.textChanged.connect(self._draft_changed)
        self.type_combo.currentTextChanged.connect(self._draft_changed)
        self.auth_combo.currentIndexChanged.connect(self._draft_changed)
        self.refresh()
        self.catalog_list.setCurrentRow(0)

    def _draft_changed(self, *_):
        self._draft_revision += 1
        self.connection_status.setText("Sin comprobar para esta configuración.")

    def _filter_catalog(self, category):
        for row, preset in enumerate(self.service.catalog()):
            self.catalog_list.item(row).setHidden(category != "Todos" and preset.category != category)

    def _select_preset(self, item, _previous=None):
        if item is None:
            return
        preset = next(p for p in self.service.catalog() if p.id == item.data(Qt.ItemDataRole.UserRole))
        self._editing = False
        self.profiles.blockSignals(True)
        self.profiles.clearSelection()
        self.profiles.setCurrentRow(-1)
        self.profiles.blockSignals(False)
        self.name_input.setText(preset.id)
        self.type_combo.setCurrentText(preset.protocol)
        self.endpoint_input.setText(preset.endpoint)
        self.auth_combo.setCurrentIndex(self.auth_combo.findData(preset.auth))
        self.key_input.clear()
        self.model_input.clear()
        self.profile_title.setText(preset.label)
        self.profile_logo.setPixmap(provider_icon(preset.id, size=28).pixmap(28, 28))
        self.profile_hint.setText("Conexión local: inicia el servidor antes de consultar." if preset.category == "Local" else "Introduce tu clave API. No se importan cuentas de suscripción.")
        self.remove_button.setEnabled(False)
        self._draft_changed()

    def _select_profile(self, item, _previous=None):
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        config = self.controller.providers().get(name)
        if not config:
            return
        if config.get("auth") == "subscription":
            self.tabs.setCurrentWidget(self.subscriptions)
            self.subscriptions.kind.setCurrentIndex(self.subscriptions.kind.findData(config["provider"]))
            self.subscriptions.name.setText(name)
            self.subscriptions.model.setCurrentText(config["model"])
            return
        self._editing = True
        self.name_input.setText(name)
        if self.type_combo.findText(config.get("provider", "")) < 0:
            self.type_combo.addItem(config.get("provider", ""))
        self.type_combo.setCurrentText(config.get("provider", "openai"))
        self.endpoint_input.setText(config.get("endpoint", ""))
        self.auth_combo.setCurrentIndex(self.auth_combo.findData(config.get("auth", "none" if config.get("provider") == "ollama" else "api_key")))
        self.model_input.clear()
        self.model_input.setCurrentText(config.get("model", ""))
        self.key_input.clear()
        self.profile_title.setText(name)
        self.profile_logo.setPixmap(provider_icon(name, config, size=28).pixmap(28, 28))
        self.profile_hint.setText("Edita los campos y guarda. Dejar la clave vacía conserva la actual.")
        self._show_storage(name)
        self.remove_button.setEnabled(True)
        self._draft_changed()
        if name in self._last_checks:
            self.connection_status.setText(self._last_checks[name])

    def _on_provider_type_changed(self, kind):
        if hasattr(self, "auth_combo"):
            self.auth_combo.setCurrentIndex(self.auth_combo.findData("none" if kind == "ollama" else "api_key"))

    def refresh(self):
        selected = self.profiles.currentItem()
        name = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.profiles.blockSignals(True)
        self.profiles.clear()
        try:
            for provider, config in self.controller.providers().items():
                check_note = self._last_checks.get(provider, "")
                suffix = f" · {check_note.split('·')[0].strip()}" if check_note else ""
                item = QListWidgetItem(provider_icon(provider, config, size=24), provider + "\n" + config.get("model", "") + suffix)
                item.setSizeHint(QSize(0, 52))
                item.setData(Qt.ItemDataRole.UserRole, provider)
                self.profiles.addItem(item)
                if provider == name:
                    self.profiles.setCurrentItem(item)
        except ValueError:
            self.connection_status.setText("No se pudo leer la configuración. El archivo se conserva.")
        self.profiles.blockSignals(False)
        self.remove_button.setEnabled(self._editing and name is not None)

    def _values(self, discovery=False):
        values = validate_config(self.name_input.text().strip(), {
            "provider": self.type_combo.currentText(),
            "endpoint": self.endpoint_input.text().strip(),
            "model": self.model_input.currentText().strip() or ("catalog-discovery" if discovery else ""),
            "auth": self.auth_combo.currentData(),
        })
        return values

    def add_provider(self):
        try:
            values = self._values()
            name = self.name_input.text().strip()
            if not self._editing and name in self.controller.providers():
                if QMessageBox.question(self, "Actualizar conexión", "Ya existe una conexión con este nombre. ¿Actualizar sus datos?") != QMessageBox.StandardButton.Yes:
                    return
            storage = self.controller.add_provider(name, values.pop("provider"), values.pop("model"),
                                                   api_key=self.key_input.text().strip() or None, **values)
        except ValueError as exc:
            self.connection_status.setText(str(exc))
            return
        except OSError:
            self.connection_status.setText("No se pudo guardar la configuración. Revisa los permisos de la carpeta de estado.")
            return
        self.key_input.clear()
        self._editing = True
        self.refresh()
        self.remove_button.setEnabled(True)
        self._show_storage(name)
        self.connection_status.setText("Conexión guardada. Consulta modelos para comprobar acceso al catálogo.")
        self.providers_changed.emit()

    def _show_keyring_banner(self):
        info = self.controller.secret_broker.keyring_status()
        prefix = "✓ " if info["available"] else "⚠ "
        self.storage_label.setText(prefix + info["detail"])

    def _show_storage(self, name):
        kr = self.controller.secret_broker.keyring_status()
        storage = self.controller.secret_broker.storage_status(name)
        kr_badge = f"Keyring: {'disponible (' + kr['backend'] + ')' if kr['available'] else 'NO disponible (' + kr['backend'] + ')'}"
        detail = {
            "keyring": "Clave guardada en el keyring del sistema.",
            "session": "⚠ Clave solo en memoria: se perderá al cerrar la sesión.",
            "missing": "Sin clave API guardada; los servicios sin autenticación no la necesitan.",
        }[storage]
        self.storage_label.setText(f"{detail}  ·  {kr_badge}")

    def inspect_models(self):
        if self._worker is not None:
            return
        try:
            values = self._values(discovery=True)
        except ValueError as exc:
            self.connection_status.setText(str(exc))
            return
        protocol = values.pop("provider")
        config = ProviderConfig(name=self.name_input.text().strip(), provider_type=protocol, **values)
        self._probe_revision = self._draft_revision
        self.connection_status.setText("Consultando catálogo…")
        self.inspect_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        worker = _InspectWorker(self.service, config, self.key_input.text().strip() or None)
        self._worker = worker
        _INSPECTIONS.add(worker)
        worker.report_ready.connect(self._inspection_finished)
        worker.finished.connect(lambda w=worker: _INSPECTIONS.discard(w))
        worker.finished.connect(self._inspection_stopped)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _cancel_inspection(self):
        if self._worker is not None:
            self._worker.cancel()

    def _inspection_finished(self, report):
        from datetime import datetime
        if self._probe_revision != self._draft_revision:
            self.connection_status.setText("La configuración cambió durante la consulta. Consulta de nuevo.")
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_text = f"{report.message} · comprobado {stamp}"
        self._last_checks[report.provider] = status_text
        self.connection_status.setText(status_text)
        if report.models:
            previous = self.model_input.currentText()
            self.model_input.clear()
            self.model_input.addItems(report.models)
            if previous:
                self.model_input.setCurrentText(previous)
        self.refresh()

    def _inspection_stopped(self):
        self._worker = None
        self.inspect_button.setEnabled(True)
        self.cancel_button.setVisible(False)

    def remove_provider(self):
        name = self.name_input.text().strip()
        if not self._editing or name not in self.controller.providers():
            return
        if QMessageBox.question(self, "Eliminar conexión", f"¿Eliminar la configuración y la clave API de {name}?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.remove_provider(name)
        except (ValueError, OSError):
            self.connection_status.setText("No se pudo eliminar la conexión; revisa el acceso al keyring.")
            return
        self._editing = False
        self.key_input.clear()
        self.model_input.clear()
        self.refresh()
        self.providers_changed.emit()
        self.connection_status.setText("Conexión eliminada.")

    def import_opencode(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar claves API de auth.json", "", "JSON (*.json)")
        if not path:
            return
        try:
            imported = self.controller.import_opencode_keys(path)
        except (OSError, ValueError):
            self.connection_status.setText("No se pudo importar. El archivo debe contener claves API; OAuth no se importa.")
            return
        self.connection_status.setText(f"Claves API importadas: {len(imported)}. Configura las conexiones correspondientes. OAuth no se importa.")
        self._show_storage(self.name_input.text().strip())
        self.refresh()
        self.providers_changed.emit()
