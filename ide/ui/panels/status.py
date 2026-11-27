"""Status panel: visual dashboard cards + raw JSON inspector.

Displays host state (runtime layers, active mode, workspace, policies,
and resident memory) in clean, structured cards alongside a raw JSON view.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                                QPlainTextEdit, QPushButton, QScrollArea,
                                QTabWidget, QVBoxLayout, QWidget)

from .. import theme


class StatusPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header with help
        top_row = QHBoxLayout()
        top_lbl = QLabel("ESTADO DEL SISTEMA (HOST STATUS)")
        top_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #6b7385; letter-spacing: 1px;")
        top_row.addWidget(top_lbl)
        top_row.addStretch(1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Actualizar estado del host")
        self.refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(self.refresh_btn)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Status: Presenta un resumen visual del estado interno del host de IsyVM:\n"
            "Modo actual (PLAN/CODER), capas de ejecución activas (Layer A/B/C), reglas de contención\n"
            "y estado del servicio residente, junto con la vista JSON completa para inspección técnica."
        )
        top_row.addWidget(self.help_button)
        layout.addLayout(top_row)

        self.tabs = QTabWidget()

        # Tab 1: Visual Dashboard
        dash_scroll = QScrollArea()
        dash_scroll.setWidgetResizable(True)
        dash_scroll.setFrameShape(QFrame.Shape.NoFrame)

        dash_content = QWidget()
        self.dash_layout = QVBoxLayout(dash_content)
        self.dash_layout.setContentsMargins(6, 6, 6, 6)
        self.dash_layout.setSpacing(12)

        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(10)
        self.dash_layout.addLayout(self.cards_grid)
        self.dash_layout.addStretch(1)

        dash_scroll.setWidget(dash_content)
        self.tabs.addTab(dash_scroll, "📊 Panel visual")

        # Tab 2: Raw JSON View (maintains full compatibility for tests/scripts)
        raw_widget = QWidget()
        raw_layout = QVBoxLayout(raw_widget)
        raw_layout.setContentsMargins(4, 4, 4, 4)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        raw_layout.addWidget(self.view, stretch=1)
        self.tabs.addTab(raw_widget, "🔍 Inspección JSON")

        layout.addWidget(self.tabs, stretch=1)
        self.refresh()

    def _create_card(self, title: str, value: str, subtitle: str = "", status_color: str = "") -> QFrame:
        card = QFrame()
        card.setObjectName("statusCard")
        l = QVBoxLayout(card)
        l.setContentsMargins(10, 8, 10, 8)
        l.setSpacing(4)

        t_lbl = QLabel(title)
        t_lbl.setObjectName("statusCardTitle")
        l.addWidget(t_lbl)

        v_lbl = QLabel(value)
        v_lbl.setTextFormat(Qt.TextFormat.PlainText)
        v_lbl.setWordWrap(True)
        v_lbl.setObjectName("statusCardValue")
        if status_color:
            v_lbl.setStyleSheet(f"color: {status_color}; font-size: 14px; font-weight: 700;")
        l.addWidget(v_lbl)

        if subtitle:
            s_lbl = QLabel(subtitle)
            s_lbl.setTextFormat(Qt.TextFormat.PlainText)
            s_lbl.setWordWrap(True)
            s_lbl.setStyleSheet("color: #9aa3b2; font-size: 11px;")
            l.addWidget(s_lbl)

        return card

    def refresh(self) -> None:
        snap = self.controller.snapshot()
        self.view.setPlainText(json.dumps(snap, indent=2, ensure_ascii=False))

        # Clear existing cards
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        mode = str(snap.get("mode", "coder")).upper()
        mode_color = theme.WARN if mode == "PLAN" else theme.ACCENT
        card_mode = self._create_card(
            "MODO DE AGENTE",
            f"● {mode}",
            "Shift+Tab para alternar PLAN / CODER",
            mode_color,
        )
        self.cards_grid.addWidget(card_mode, 0, 0)

        # Runtime layers
        runtimes = snap.get("runtime", {})
        layers_str = " · ".join(f"{k.upper()}: {'ON' if v else 'OFF'}" for k, v in runtimes.items())
        layer_notes = (
            "Disponibilidad del adaptador; no demuestra aislamiento del sistema operativo.\n"
            "LAYER_B (WASM) y LAYER_C (VM) están OFF por diseño en esta build (sin adaptador WASM/VM instalado); "
            "los comandos aislados usan LINUX_ISOLATED (bwrap/namespaces sin red)."
        )
        card_layers = self._create_card(
            "CAPAS DE RUNTIME",
            layers_str or "layer_a=ON",
            layer_notes,
            theme.OK,
        )
        self.cards_grid.addWidget(card_layers, 0, 1)

        # Workspace
        working_dir = str(snap.get("working_dir", ""))
        card_ws = self._create_card(
            "WORKSPACE ACTIVO",
            working_dir.split("/")[-1] or working_dir,
            working_dir,
            theme.TEXT,
        )
        self.cards_grid.addWidget(card_ws, 1, 0)

        # Policies count
        policies = snap.get("policy", [])
        allow_count = sum(1 for p in policies if p.get("allowed"))
        card_pol = self._create_card(
            "POLÍTICAS DEL IDE",
            f"{len(policies)} Reglas activas",
            f"{allow_count} permitidas · {len(policies) - allow_count} restringidas",
            theme.TEXT,
        )
        self.cards_grid.addWidget(card_pol, 1, 1)

        # Providers
        providers = snap.get("providers", {})
        prov_count = len(providers) if isinstance(providers, dict) else 0
        card_prov = self._create_card(
            "PROVEEDORES CONFIGURADOS",
            f"{prov_count} Configurado(s)",
            "Configura en el panel Config o ventana flotante",
            theme.TEXT,
        )
        self.cards_grid.addWidget(card_prov, 2, 0)

        # Resident State
        resident_stat = snap.get("resident", {})
        comp_count = resident_stat.get("components", 0)
        res_note = (
            f"{comp_count} registros de componentes; no es un servicio de red"
            if comp_count > 0
            else "0 registros de componentes (aún no se ha escaneado este proyecto; no es un servicio de red)"
        )
        card_res = self._create_card(
            "SERVICIO RESIDENTE",
            "Memoria local · lectura",
            res_note,
            theme.ACCENT,
        )
        scan_btn = QPushButton("Escanear proyecto ahora")
        scan_btn.setToolTip("Indexa los componentes del proyecto activo en la memoria local residente")
        scan_btn.clicked.connect(self._scan_resident)
        card_res.layout().addWidget(scan_btn)
        self.cards_grid.addWidget(card_res, 2, 1)

    def _scan_resident(self) -> None:
        try:
            self.controller.resident_scan()
        except Exception:
            pass
        self.refresh()
