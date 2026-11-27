"""Tool calls & Management panel.

Displays real-time tool execution logs with evidence, and allows operators
to inspect and persistently enable/disable implemented tools for the agent.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                                QFormLayout, QHBoxLayout, QHeaderView,
                                QLabel, QLineEdit, QMessageBox,
                                QPlainTextEdit, QPushButton, QSplitter,
                                QTabWidget, QTableWidget, QTableWidgetItem,
                                QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                                QWidget)

from .. import theme
from ..tool_presentation import present_tool
from core.agent.run import AVAILABLE_TOOLS


# Schemas come from the agent runtime catalog, rather than a second handwritten list.
ALL_CATALOG_TOOLS = [{**tool["function"], "builtin": True} for tool in AVAILABLE_TOOLS]


class AddToolDialog(QDialog):
    """Dialog to register a new tool schema into the catalog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Añadir Nueva Tool — Formato JSON Schema")
        self.resize(520, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ej. web_search")
        form.addRow("Nombre de tool:", self.name_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Descripción de lo que hace la tool...")
        form.addRow("Descripción:", self.desc_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("Parámetros (JSON Schema):"))
        self.params_edit = QPlainTextEdit()
        self.params_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        default_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Término de búsqueda"}
            },
            "required": ["query"]
        }
        self.params_edit.setPlainText(json.dumps(default_schema, indent=2))
        layout.addWidget(self.params_edit, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Añadir Tool")
        save_btn.setProperty("variant", "primary")
        save_btn.clicked.connect(self._validate_and_accept)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Campo requerido", "El nombre de la tool no puede estar vacío.")
            return
        try:
            params = json.loads(self.params_edit.toPlainText())
        except Exception as exc:
            QMessageBox.warning(self, "JSON Inválido", f"El JSON Schema de parámetros no es válido:\n{exc}")
            return
        self.tool_data = {
            "name": name,
            "description": self.desc_edit.text().strip(),
            "builtin": False,
            "parameters": params,
        }
        self.accept()


class ToolsPanel(QWidget):
    """Tool execution log + Tool management catalog with enable/disable switches."""

    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.controller = controller
        self.tools_catalog = [{**tool, "available": False, "enabled": False} for tool in ALL_CATALOG_TOOLS]
        self.enabled_tools: set[str] = {
            t["name"] for t in self.tools_catalog if t.get("enabled", False)
        }
        self._pending: dict[str, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header with help
        top_row = QHBoxLayout()
        top_lbl = QLabel("HERRAMIENTAS & EJECUCIÓN (TOOLS)")
        top_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #6b7385; letter-spacing: 1px;")
        top_row.addWidget(top_lbl)
        top_row.addStretch(1)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Tool calls: Muestra el registro en tiempo real de cada llamada a herramienta propuesta por el agente.\n"
            "Gestión: habilita herramientas implementadas por proyecto. Un JSON Schema no ejecuta una herramienta."
        )
        top_row.addWidget(self.help_button)
        layout.addLayout(top_row)

        self.tabs = QTabWidget()

        # Tab 1: Execution Log
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(4, 4, 4, 4)
        log_layout.setSpacing(6)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Tool", "Status", "Detail", "Actor"])
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemDoubleClicked.connect(self._show_details)
        log_layout.addWidget(self.tree, stretch=1)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Limpiar historial")
        clear_btn.clicked.connect(self.tree.clear)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
        log_layout.addLayout(btn_row)

        self.tabs.addTab(log_widget, "📋 Historial de ejecución")

        # Tab 2: Catalog & Configuration
        mgmt_widget = QWidget()
        mgmt_layout = QVBoxLayout(mgmt_widget)
        mgmt_layout.setContentsMargins(4, 4, 4, 4)
        mgmt_layout.setSpacing(8)

        mgmt_top = QHBoxLayout()
        mgmt_info = QLabel("Activa o desactiva las herramientas que el agente tiene disponibles:")
        mgmt_info.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        mgmt_top.addWidget(mgmt_info)
        mgmt_top.addStretch(1)

        add_tool_btn = QPushButton("➕ Añadir Tool...")
        add_tool_btn.setEnabled(False)
        add_tool_btn.setToolTip("Pendiente: registrar un adaptador ejecutable. Un schema por sí solo no habilita una herramienta.")
        add_tool_btn.clicked.connect(self._open_add_tool)
        mgmt_top.addWidget(add_tool_btn)
        mgmt_layout.addLayout(mgmt_top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Activa", "Nombre", "Tipo", "Descripción"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        thdr = self.table.horizontalHeader()
        thdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(self._show_schema)
        mgmt_layout.addWidget(self.table, stretch=1)

        self.tabs.addTab(mgmt_widget, "⚙️ Gestión de Tools (Activar / Desactivar)")

        # Tab 3: ISyCo & ISyMCP Ecosystem Integration
        eco_widget = QWidget()
        eco_layout = QVBoxLayout(eco_widget)
        eco_layout.setContentsMargins(4, 4, 4, 4)
        eco_layout.setSpacing(8)
        eco_top = QHBoxLayout()
        self.eco_summary = QLabel("Integración con herramientas locales y públicas de ISyCo / ISyMCP:")
        self.eco_summary.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        eco_top.addWidget(self.eco_summary, 1)
        self.eco_refresh_btn = QPushButton("Comprobar herramientas")
        self.eco_refresh_btn.setProperty("variant", "primary")
        self.eco_refresh_btn.clicked.connect(self.refresh_ecosystem)
        eco_top.addWidget(self.eco_refresh_btn)
        eco_layout.addLayout(eco_top)

        self.eco_table = QTableWidget(0, 4)
        self.eco_table.setHorizontalHeaderLabels(["Herramienta", "Estado", "Ruta / Endpoint", "Descripción"])
        self.eco_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.eco_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        ehdr = self.eco_table.horizontalHeader()
        ehdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        ehdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ehdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ehdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        eco_layout.addWidget(self.eco_table, stretch=1)

        self.mcp_preview = QPlainTextEdit()
        self.mcp_preview.setReadOnly(True)
        self.mcp_preview.setMaximumHeight(130)
        self.mcp_preview.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        eco_layout.addWidget(self.mcp_preview)
        self.tabs.addTab(eco_widget, "🔌 ISyCo && ISyMCP")

        layout.addWidget(self.tabs, stretch=1)
        self._populate_tools_table()
        self.refresh_settings()
        self.refresh_ecosystem()
        self.tabs.setCurrentIndex(1)

    def refresh_ecosystem(self) -> None:
        """Inspect installed ISyCo public tools & ISyMCP hub without mutating them or leaking secrets."""
        import shutil
        import socket
        from datetime import datetime
        from pathlib import Path

        def _port_open(port: int) -> bool:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    return True
            except OSError:
                return False

        def _find_bin(name: str) -> str:
            found = shutil.which(name)
            if found:
                return found
            local = Path.home() / ".local" / "bin" / name
            return str(local) if local.exists() else ""

        rows = []
        hub_up = _port_open(8798)
        mon_up = _port_open(8799)
        isymcp_bin = _find_bin("isymcp")
        mcp_cfg = Path.home() / ".config" / "isycode" / "mcp.json"
        rows.append((
            "ISyMCP Hub",
            "ACTIVO (:8798)" if hub_up else ("Instalado (detenido)" if isymcp_bin else "No instalado"),
            "http://127.0.0.1:8798" if hub_up else (isymcp_bin or "—"),
            f"Gateway MCP local de ISyCo · monitor :8799 {'ON' if mon_up else 'OFF'} · mcp.json {'sí' if mcp_cfg.is_file() else 'no'}",
        ))
        for name, desc in (
            ("isymem", "Memoria compartida multi-harness (docs/agent/memory/)"),
            ("ziggrep", "Búsqueda rápida de código compatible con grep/rg en Zig"),
            ("isycode", "CLI/TUI oficial de ISyCode (DannyBaanks/ISyCode)"),
            ("isyco", "CLI del monorepo de investigación ISyCo"),
            ("gh", "GitHub CLI (catálogo público y sincronización de DannyBaanks)"),
        ):
            path = _find_bin(name)
            rows.append((name, "Disponible" if path else "No encontrado", path or "—", desc))

        self.eco_table.setRowCount(len(rows))
        for idx, (tool_name, state, loc, desc) in enumerate(rows):
            self.eco_table.setItem(idx, 0, QTableWidgetItem(tool_name))
            self.eco_table.setItem(idx, 1, QTableWidgetItem(state))
            self.eco_table.setItem(idx, 2, QTableWidgetItem(loc))
            self.eco_table.setItem(idx, 3, QTableWidgetItem(desc))

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        avail = sum(1 for _, st, _, _ in rows if "Disponible" in st or "ACTIVO" in st or "Instalado" in st)
        self.eco_summary.setText(f"Ecosistema ISyCo · {avail}/{len(rows)} integraciones detectadas (comprobado {stamp})")

        if mcp_cfg.is_file():
            try:
                data = json.loads(mcp_cfg.read_text(encoding="utf-8"))
                servers = data.get("mcpServers") or data.get("servers") or data
                if isinstance(servers, dict):
                    names = list(servers.keys())
                    self.mcp_preview.setPlainText(
                        f"Servidores MCP registrados en {mcp_cfg}:\n"
                        + ("\n".join(f"  • {k}" for k in names) if names else "  (ninguno)")
                        + "\n\n(Valores de entorno/tokens omitidos por seguridad.)"
                    )
                else:
                    self.mcp_preview.setPlainText(f"Archivo {mcp_cfg} encontrado.")
            except Exception:
                self.mcp_preview.setPlainText(f"No se pudo leer {mcp_cfg} como JSON.")
        else:
            self.mcp_preview.setPlainText("No se encontró ~/.config/isycode/mcp.json. ISyMCP puede conectarse en cuanto exista configuración MCP.")

    def _populate_tools_table(self) -> None:
        self.table.setRowCount(len(self.tools_catalog))
        for row, t in enumerate(self.tools_catalog):
            name = t["name"]
            is_enabled = name in self.enabled_tools

            # Checkbox widget
            cb_container = QWidget()
            cb_layout = QHBoxLayout(cb_container)
            cb_layout.setContentsMargins(6, 0, 6, 0)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox()
            cb.setChecked(is_enabled)
            cb.setEnabled(bool(t.get("available")))
            if not t.get("available"):
                cb.setToolTip("No disponible: falta un runtime aislado habilitado.")
            cb.toggled.connect(lambda checked, n=name: self._toggle_tool(n, checked))
            cb_layout.addWidget(cb)
            self.table.setCellWidget(row, 0, cb_container)

            # Name
            self.table.setItem(row, 1, QTableWidgetItem(name))
            # Type (Built-in / Custom)
            tipo = "Nativa" if t.get("available") else "No disponible"
            self.table.setItem(row, 2, QTableWidgetItem(tipo))
            # Description
            self.table.setItem(row, 3, QTableWidgetItem(t.get("description", "")))

    def refresh_settings(self) -> None:
        if self.controller is None:
            return
        try:
            self.tools_catalog = self.controller.tool_settings.catalog()
        except (ValueError, OSError):
            self.tools_catalog = [{**tool, "available": False, "enabled": False} for tool in ALL_CATALOG_TOOLS]
        self.enabled_tools = {t["name"] for t in self.tools_catalog if t.get("enabled")}
        self._populate_tools_table()

    def _toggle_tool(self, name: str, enabled: bool) -> None:
        if self.controller is None:
            return
        try:
            self.controller.tool_settings.set_enabled(name, enabled)
        except (ValueError, OSError):
            QMessageBox.warning(self, "Herramientas", "No se pudo guardar el switch del proyecto.")
            self.refresh_settings()
            return
        if enabled:
            self.enabled_tools.add(name)
        else:
            self.enabled_tools.discard(name)

    def _open_add_tool(self) -> None:
        QMessageBox.information(self, "Integraciones", "Las herramientas personalizadas requieren un adaptador ejecutable del host. Integración pendiente.")

    def _show_schema(self, item: QTableWidgetItem) -> None:
        row = item.row()
        tool_data = self.tools_catalog[row]
        body = (
            f"Herramienta: {tool_data['name']}\n"
            f"Tipo: {'Nativa' if tool_data.get('builtin') else 'Personalizada'}\n"
            f"Descripción: {tool_data.get('description', '')}\n\n"
            f"--- JSON Schema de Parámetros ---\n"
            f"{json.dumps(tool_data.get('parameters', {}), indent=2, ensure_ascii=False)}"
        )
        QMessageBox.information(self, f"Tool: {tool_data['name']}", body)

    # --- Tool Call Execution Log handlers (Maintains full existing API) ---

    def on_tool_call(self, event: dict) -> None:
        args = event.get("arguments", {})
        view = present_tool(event.get("tool", "?"), args)
        args_text = view["summary"]
        item = QTreeWidgetItem([
            view["title"],
            view["status"],
            args_text,
            "POLICY → RUNTIME",
        ])
        self.tree.addTopLevelItem(item)
        self._pending[event.get("id", "")] = item

    def on_tool_result(self, event: dict) -> None:
        item = self._pending.pop(event.get("id", ""), None)
        if item is None:
            item = QTreeWidgetItem([event.get("tool", "?"), "", "", ""])
            self.tree.addTopLevelItem(item)
        view = event.get("presentation") or present_tool(event.get("tool", "?"), event.get("arguments", {}), event)
        item.setText(0, view["title"])
        item.setText(1, view["status"])
        item.setText(2, view["summary"].replace("\n", " · "))
        actor = "CODER"
        evidence = event.get("evidence") or {}
        if evidence.get("actor"):
            actor = str(evidence["actor"])
        item.setText(3, actor)
        item.setToolTip(2, (event.get("stdout") or "")[:8000])
        item.setData(0, Qt.ItemDataRole.UserRole, event)

    def _show_details(self, item: QTreeWidgetItem, _column: int) -> None:
        event = item.data(0, Qt.ItemDataRole.UserRole)
        if not event:
            return
        body = (
            f"tool: {event.get('tool')}\n"
            f"success: {event.get('success')}\n"
            f"returncode: {event.get('returncode')}\n"
            f"error_code: {event.get('error_code')}\n\n"
            f"--- Argumentos originales ---\n{json.dumps(event.get('arguments', {}), indent=2, ensure_ascii=False)}\n\n"
            f"--- stdout {'(vista acotada)' if event.get('stdout_truncated') else ''} ---\n{event.get('stdout', '')}\n\n"
            f"--- stderr {'(vista acotada)' if event.get('stderr_truncated') else ''} ---\n{event.get('stderr', '')}\n\n"
            f"--- evidence ---\n"
            f"{json.dumps(event.get('evidence', {}), indent=2, ensure_ascii=False)}"
        )
        QMessageBox.information(self, "Tool execution evidence", body)
