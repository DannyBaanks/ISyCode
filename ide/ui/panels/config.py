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
    models_discovered = Signal(str, list)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.service = controller.provider_service
        self._worker = None
        self._editing = False
        self._draft_revision = 0
        self._probe_revision = 0
        self._last_checks: dict[str, str] = {}
        self._discovered_cache: dict[str, list[str]] = {}
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
        self.refresh_button.setProperty("variant", "ghost")
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
        self.health_pill = QLabel("○ Sin comprobar")
        self.health_pill.setStyleSheet("padding: 4px 10px; border-radius: 10px; background: #162133; color: #94a3b8; font-size: 12px; font-weight: 600;")
        heading.addWidget(self.health_pill)
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
        self.inspect_button = QPushButton("Descubrir modelos")
        self.inspect_button.clicked.connect(self.inspect_models)
        self.ping_button = QPushButton("Probar modelo (Pong)")
        self.ping_button.setToolTip("Envía un pong real al modelo seleccionado, mide la latencia y guarda el resultado o error")
        self.ping_button.clicked.connect(self.ping_selected_model)
        self.ping_pill = QLabel("")
        self.ping_pill.setVisible(False)
        self.cancel_button = QPushButton("Cancelar consulta")
        self.cancel_button.clicked.connect(self._cancel_inspection)
        self.cancel_button.setVisible(False)
        query_row.addWidget(self.inspect_button)
        query_row.addWidget(self.ping_button)
        query_row.addWidget(self.ping_pill)
        query_row.addWidget(self.cancel_button)
        query_row.addStretch()
        form_box.addLayout(query_row)

        # Searchable model picker card
        picker_frame = QFrame()
        picker_frame.setObjectName("statusCard")
        picker_box = QVBoxLayout(picker_frame)
        picker_box.setContentsMargins(12, 10, 12, 10)
        picker_box.setSpacing(6)
        picker_hdr = QHBoxLayout()
        self.picker_title = QLabel("Modelos disponibles (clic para elegir)")
        self.picker_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        picker_hdr.addWidget(self.picker_title, 1)
        self.model_filter = QLineEdit()
        self.model_filter.setPlaceholderText("Filtrar modelos (ej. llama, qwen, claude)…")
        self.model_filter.setMaximumWidth(260)
        self.model_filter.textChanged.connect(self._filter_model_browser)
        picker_hdr.addWidget(self.model_filter)
        picker_box.addLayout(picker_hdr)
        self.model_browser = QListWidget()
        self.model_browser.setMaximumHeight(140)
        self.model_browser.itemClicked.connect(
            lambda it: self.model_input.setCurrentText(it.data(Qt.ItemDataRole.UserRole)) if it.data(Qt.ItemDataRole.UserRole) else None
        )
        picker_box.addWidget(self.model_browser)
        form_box.addWidget(picker_frame)
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
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        actions.addWidget(self.add_button)
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
        self.import_button.setProperty("variant", "ghost")
        self.help_button = QPushButton("Ayuda de conexión")
        self.help_button.clicked.connect(lambda: QMessageBox.information(
            self, "Providers", "1. Elige un provider.\n2. Introduce endpoint y autenticación.\n3. Consulta modelos o escribe el ID.\n4. Guarda la conexión y selecciónala en la barra superior.\n\nConsultar modelos no envía un prompt ni verifica compatibilidad con herramientas."
        ))
        self.help_button.setProperty("variant", "ghost")
        extra_row = QHBoxLayout()
        extra_row.addWidget(self.import_button)
        extra_row.addWidget(self.help_button)
        extra_row.addStretch(1)
        form_box.addLayout(extra_row)
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
        self.profile_title.setText(f"Nueva conexión · {preset.label}")
        self.profile_logo.setPixmap(provider_icon(preset.id, size=28).pixmap(28, 28))
        self.profile_hint.setText("Conexión local: inicia el servidor antes de consultar." if preset.category == "Local" else "Introduce tu clave API. No se importan cuentas de suscripción.")
        self.remove_button.setEnabled(False)
        self.remove_button.setVisible(False)
        self.add_button.setText("Añadir conexión")
        self._populate_model_browser([])
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
        self.profile_title.setText(f"Editar conexión · {name}")
        self.profile_logo.setPixmap(provider_icon(name, config, size=28).pixmap(28, 28))
        self.profile_hint.setText("Edita los campos y guarda. Dejar la clave vacía conserva la actual.")
        self._show_storage(name)
        self.remove_button.setEnabled(True)
        self.remove_button.setVisible(True)
        self.add_button.setText("Guardar cambios")
        self._draft_changed()
        if name in self._last_checks:
            self.connection_status.setText(self._last_checks[name])
        if name in self._discovered_cache:
            self._populate_model_browser(self._discovered_cache[name])
            self._set_health_pill("ok", f"● {len(self._discovered_cache[name])} modelos")
        else:
            self._populate_model_browser([config.get("model", "")] if config.get("model") else [])
            # Auto-discover models in background when credentials exist or auth is none
            has_auth = config.get("auth") == "none" or self.controller.secret_broker.has_key(name)
            if has_auth and self._worker is None:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(50, self.inspect_models)

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

    def _set_health_pill(self, state: str, text: str) -> None:
        if not hasattr(self, "health_pill"):
            return
        styles = {
            "ok": "padding: 4px 10px; border-radius: 10px; background: #0d3326; color: #34d399; font-size: 11px; font-weight: 700;",
            "loading": "padding: 4px 10px; border-radius: 10px; background: #0d2a3d; color: #38bdf8; font-size: 11px; font-weight: 700;",
            "error": "padding: 4px 10px; border-radius: 10px; background: #3b141a; color: #fb7185; font-size: 11px; font-weight: 700;",
            "idle": "padding: 4px 10px; border-radius: 10px; background: #162133; color: #94a3b8; font-size: 11px; font-weight: 600;",
        }
        self.health_pill.setText(text)
        self.health_pill.setStyleSheet(styles.get(state, styles["idle"]))

    def _populate_model_browser(self, models: list[str]) -> None:
        if not hasattr(self, "model_browser"):
            return
        self._current_browser_models = list(models)
        self._filter_model_browser(self.model_filter.text() if hasattr(self, "model_filter") else "")

    def _filter_model_browser(self, text: str) -> None:
        if not hasattr(self, "model_browser"):
            return
        from core.provider_service import ModelPingStore
        ping_map = ModelPingStore().load()
        prov = self.name_input.text().strip()
        q = text.strip().casefold()
        all_models = getattr(self, "_current_browser_models", [])
        filtered = [m for m in all_models if not q or q in m.casefold()]
        self.model_browser.clear()
        for m in filtered[:250]:
            entry = ping_map.get(f"{prov}::{m}") if prov else None
            label = m
            if isinstance(entry, dict):
                if entry.get("ok"):
                    label = f"{m}   ·   ✓ {entry.get('latency_ms', 0)} ms"
                else:
                    label = f"{m}   ·   ✗ error"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, m)
            if isinstance(entry, dict) and entry.get("error"):
                item.setToolTip(f"Último error ({entry.get('checked_at', '')}): {entry.get('error')}")
            elif isinstance(entry, dict) and entry.get("ok"):
                item.setToolTip(f"Último pong OK: {entry.get('latency_ms', 0)} ms ({entry.get('checked_at', '')})")
            self.model_browser.addItem(item)
        if not filtered:
            hint = QListWidgetItem("Sin coincidencias para el filtro." if all_models else "Aún no hay modelos. Pulsa «Descubrir modelos» para consultarlos.")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self.model_browser.addItem(hint)
        if hasattr(self, "picker_title"):
            self.picker_title.setText(f"Modelos disponibles ({len(filtered)}/{len(all_models)}) · clic para elegir")

    def refresh_ping_badges(self) -> None:
        self._filter_model_browser(self.model_filter.text() if hasattr(self, "model_filter") else "")

    def ping_selected_model(self) -> None:
        from core.provider_service import ModelPingStore
        name = self.name_input.text().strip()
        model = self.model_input.currentText().strip()
        if not name or not model:
            self.connection_status.setText("Indica nombre de conexión y modelo antes de probar (Pong).")
            return
        if name not in self.controller.providers():
            self.connection_status.setText("Guarda primero la conexión para probar el modelo con Pong.")
            return
        self.ping_button.setEnabled(False)
        self.ping_pill.setVisible(True)
        self.ping_pill.setText("… enviando pong")
        self.ping_pill.setStyleSheet(
            "padding: 4px 10px; border-radius: 10px; background: #0d2a3d; color: #38bdf8; font-size: 11px; font-weight: 700;"
        )

        class _ConfigPingWorker(QThread):
            done = Signal(object)

            def __init__(self, service, prov, mod):
                super().__init__()
                self._service = service
                self._prov = prov
                self._mod = mod

            def run(self):
                import asyncio
                res = asyncio.run(self._service.ping_model(self._prov, self._mod, store=ModelPingStore()))
                self.done.emit(res)

        worker = _ConfigPingWorker(self.service, name, model)
        _INSPECTIONS.add(worker)

        def _done(res):
            self.ping_button.setEnabled(True)
            if res.ok:
                self.ping_pill.setText(f"✓ {res.latency_ms} ms · {res.reply[:24]}")
                self.ping_pill.setStyleSheet(
                    "padding: 4px 10px; border-radius: 10px; background: #0d3326; color: #34d399; font-size: 11px; font-weight: 700;"
                )
                self.connection_status.setText(f"Pong OK en {res.latency_ms} ms ({res.checked_at}). Respuesta: {res.reply}")
            else:
                self.ping_pill.setText(f"✗ error ({res.latency_ms} ms)")
                self.ping_pill.setStyleSheet(
                    "padding: 4px 10px; border-radius: 10px; background: #3b141a; color: #fb7185; font-size: 11px; font-weight: 700;"
                )
                self.connection_status.setText(f"Pong falló ({res.latency_ms} ms): {res.error}")
            self.refresh_ping_badges()

        worker.done.connect(_done)
        worker.finished.connect(lambda w=worker: _INSPECTIONS.discard(w))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def discover_models_silent(self, provider_name: str, callback=None) -> None:
        """Background model discovery for error-recovery switcher without changing form selection."""
        try:
            config = self.controller.provider_registry.get_config(provider_name)
        except ValueError:
            return
        worker = _InspectWorker(self.service, config, None)
        _INSPECTIONS.add(worker)
        def _done(report):
            if report.models:
                models_list = list(report.models)
                self._discovered_cache[provider_name] = models_list
                self.models_discovered.emit(provider_name, models_list)
                if callback:
                    callback(models_list)
        worker.report_ready.connect(_done)
        worker.finished.connect(lambda w=worker: _INSPECTIONS.discard(w))
        worker.finished.connect(worker.deleteLater)
        worker.start()

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
        self.connection_status.setText("Descubriendo modelos…")
        self._set_health_pill("loading", "◌ Descubriendo…")
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
            models_list = list(report.models)
            self._discovered_cache[report.provider] = models_list
            self._set_health_pill("ok", f"● {len(models_list)} modelos")
            previous = self.model_input.currentText()
            self.model_input.clear()
            self.model_input.addItems(models_list)
            if previous:
                self.model_input.setCurrentText(previous)
            self._populate_model_browser(models_list)
            self.models_discovered.emit(report.provider, models_list)
        else:
            self._set_health_pill("error" if report.state not in {"catalog_available", "unsupported_listing"} else "idle", f"● {report.state}")
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
