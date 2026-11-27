"""Native appearance settings and explicit additive legacy migration."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSpinBox, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)
import json
from pathlib import Path

from core.ide_state import migrate_project_metadata, migrate_provider_metadata
from core.ui_preferences import UiPreferences


class SettingsPanel(QWidget):
    appearance_changed = Signal(dict)
    migration_done = Signal()
    workspace_change_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.busy_guard = lambda: False
        self.preferences = UiPreferences()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        title = QLabel("Ajustes")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Tu espacio de trabajo, tus preferencias")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        sections = QVBoxLayout(body)
        sections.setSpacing(20)
        appearance = QGroupBox("Interfaz")
        form = QFormLayout(appearance)
        form.setContentsMargins(20, 22, 20, 22)
        form.setSpacing(16)
        self.view = QComboBox()
        self.view.addItem("Conversación", "conversation")
        self.view.addItem("Código + chat", "code")
        form.addRow("Vista inicial", self.view)
        self.remember = QCheckBox("Recordar la última vista")
        form.addRow("", self.remember)
        self.font_size = QSpinBox()
        self.font_size.setRange(9, 24)
        self.font_size.setSuffix(" pt")
        form.addRow("Fuente del editor", self.font_size)
        save = QPushButton("Guardar preferencias")
        save.setProperty("variant", "primary")
        save.clicked.connect(self.save)
        form.addRow("", save)
        sections.addWidget(appearance)

        ws_group = QGroupBox("Proyecto / Workspace activo")
        ws_box = QVBoxLayout(ws_group)
        ws_box.setContentsMargins(20, 22, 20, 22)
        self.workspace_info = QLabel(str(self.controller.working_dir))
        self.workspace_info.setTextFormat(Qt.TextFormat.PlainText)
        self.workspace_info.setWordWrap(True)
        ws_box.addWidget(self.workspace_info)
        ws_btn = QPushButton("Cambiar carpeta de proyecto…")
        ws_btn.clicked.connect(self.workspace_change_requested.emit)
        ws_box.addWidget(ws_btn)
        sections.addWidget(ws_group)

        permissions = QGroupBox("Permisos de comandos · este proyecto")
        permission_box = QVBoxLayout(permissions)
        permission_box.setContentsMargins(20, 22, 20, 22)
        hint = QLabel("Permitir siempre conserva solo argv exacto + ejecutable/hash + cwd + perfil. Revocar afecta a las siguientes ejecuciones; los cambios de archivos siguen necesitando aprobación.")
        hint.setWordWrap(True)
        permission_box.addWidget(hint)
        self.grants_empty_label = QLabel("Sin permisos permanentes todavía: se agregan aquí cuando eliges «Permitir siempre» al aprobar un comando en el chat.")
        self.grants_empty_label.setWordWrap(True)
        self.grants_empty_label.setStyleSheet("color: #9aa3b2; font-size: 11px;")
        permission_box.addWidget(self.grants_empty_label)
        self.grants = QTreeWidget()
        self.grants.setHeaderLabels(["Comando", "Estado"])
        self.grants.setMinimumHeight(160)
        permission_box.addWidget(self.grants)
        revoke = QPushButton("Revocar permiso seleccionado")
        revoke.setProperty("variant", "danger")
        revoke.clicked.connect(self.revoke_grant)
        permission_box.addWidget(revoke)
        refresh = QPushButton("Actualizar permisos")
        refresh.clicked.connect(self.refresh_grants)
        permission_box.addWidget(refresh)
        sections.addWidget(permissions)
        migration = QGroupBox("Migración desde IsyVM")
        box = QVBoxLayout(migration)
        box.setContentsMargins(20, 22, 20, 22)
        self.migration_state_label = QLabel("")
        self.migration_state_label.setWordWrap(True)
        self.migration_state_label.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        box.addWidget(self.migration_state_label)
        hint = QLabel("Importa metadatos públicos y estado conocido. Conserva el origen, los conflictos y las credenciales existentes.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        global_button = QPushButton("Importar configuración pública de providers")
        global_button.clicked.connect(lambda: self.migrate(False))
        box.addWidget(global_button)
        project_button = QPushButton("Importar estado antiguo de este proyecto")
        project_button.clicked.connect(lambda: self.migrate(True))
        box.addWidget(project_button)
        sections.addWidget(migration)
        self.notice = QLabel("")
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        sections.addWidget(self.notice)
        sections.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.refresh()

    def refresh(self):
        try:
            values = self.preferences.load()
        except (OSError, ValueError):
            values = self.preferences.defaults
            self.notice.setText("No se pudieron leer las preferencias; el archivo existente se conserva.")
        self.view.setCurrentIndex(self.view.findData(values["view"]))
        self.remember.setChecked(values["remember_view"])
        self.font_size.setValue(values["editor_font_size"])
        if hasattr(self, "workspace_info"):
            self.workspace_info.setText(f"Carpeta activa: {self.controller.working_dir}")
        if hasattr(self, "migration_state_label"):
            has_legacy_global = (Path.home() / ".isyvm" / "config.yaml").is_file()
            has_legacy_proj = (self.controller.working_dir / ".isyvm").is_dir()
            if has_legacy_global or has_legacy_proj:
                parts = []
                if has_legacy_global:
                    parts.append("config global legacy detectada (~/.isyvm)")
                if has_legacy_proj:
                    parts.append("estado legacy en proyecto (.isyvm/)")
                self.migration_state_label.setText("Estado: Pendiente / disponible (" + ", ".join(parts) + ")")
            else:
                self.migration_state_label.setText("Estado: No aplica (no se detectó estado legacy de IsyVM en este proyecto ni en ~/.isyvm)")
        self.refresh_grants()

    def refresh_grants(self):
        self.grants.clear()
        try:
            records = self.controller.tool_execution.grants.list()
        except (OSError, ValueError):
            self.notice.setText("No se pudo leer el registro de permisos; no se concede ninguno por defecto.")
            return
        if hasattr(self, "grants_empty_label"):
            self.grants_empty_label.setVisible(not records)
        for record in records:
            identity = record["identity"]
            item = QTreeWidgetItem([json.dumps(identity["argv"], ensure_ascii=False), "Activo" if record["enabled"] else "Revocado"])
            item.setData(0, Qt.ItemDataRole.UserRole, record["key"])
            item.setToolTip(0, json.dumps(identity, ensure_ascii=False, indent=2))
            self.grants.addTopLevelItem(item)

    def revoke_grant(self):
        item = self.grants.currentItem()
        if item is None:
            return
        try:
            self.controller.tool_execution.grants.revoke(item.data(0, Qt.ItemDataRole.UserRole))
        except (OSError, ValueError):
            self.notice.setText("No se pudo revocar el permiso. Vuelve a consultar su estado.")
            return
        self.refresh_grants()
        self.notice.setText("Permiso revocado. Un proceso ya iniciado termina o se detiene con Detener.")

    def save(self):
        try:
            values = self.preferences.save(view=self.view.currentData(), remember_view=self.remember.isChecked(),
                                            editor_font_size=self.font_size.value())
        except (OSError, ValueError):
            self.notice.setText("No se pudieron guardar las preferencias. Revisa el estado global del IDE.")
            return
        self.appearance_changed.emit(values)
        self.notice.setText("Preferencias guardadas.")

    def migrate(self, project):
        if self.busy_guard():
            self.notice.setText("Espera a que termine el agente o la operación Git antes de migrar estado.")
            return
        try:
            report = (migrate_project_metadata(self.controller.working_dir) if project else migrate_provider_metadata())
        except (OSError, ValueError):
            self.notice.setText("La migración no pudo terminar. Conserva origen y destino; revisa el manifiesto antes de volver a intentarlo.")
            return
        self.notice.setText("Migración: " + report["status"] + "\nImportados: " + ", ".join(report["imported"]) +
                            "\nConflictos conservados: " + ", ".join(report["conflicts"]))
        self.migration_done.emit()
