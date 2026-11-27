"""Resident panel: structural resident status, query, scan and sessions."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

CATEGORIES = [
    "architecture", "component", "contract", "constraint", "protected",
    "decision", "change", "verification", "plan", "unknown", "general",
]


class ResidentPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.scan_button = QPushButton("Self-scan (deterministic)")
        self.scan_button.setToolTip("Ejecuta un auto-escaneo determinista del workspace para mapear componentes")
        self.scan_button.clicked.connect(self.run_scan)
        row.addWidget(self.scan_button)
        self.status_button = QPushButton("Status")
        self.status_button.setToolTip("Muestra el estado del servicio residente")
        self.status_button.clicked.connect(self.show_status)
        row.addWidget(self.status_button)
        row.addStretch(1)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Resident: Servicio estructural persistente que almacena conocimiento del proyecto,\n"
            "sesiones de ejecución, planes de trabajo y restricciones de arquitectura en modo solo lectura.\n"
            "Permite consultar archivos relevantes y verificar zonas protegidas."
        )
        row.addWidget(self.help_button)
        layout.addLayout(row)

        query_row = QHBoxLayout()
        query_row.addWidget(QLabel("Query:"))
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("intent (e.g. modify core/runtime/base.py)")
        self.query_input.returnPressed.connect(self.run_query)
        query_row.addWidget(self.query_input, stretch=1)
        self.query_button = QPushButton("Query")
        self.query_button.clicked.connect(self.run_query)
        query_row.addWidget(self.query_button)
        layout.addLayout(query_row)

        split = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Sessions"))
        self.sessions = QListWidget()
        self.sessions.itemClicked.connect(self.show_session)
        left_layout.addWidget(self.sessions, stretch=1)
        left_layout.addWidget(QLabel("Plans"))
        self.plans = QListWidget()
        self.plans.itemClicked.connect(self.show_plan)
        left_layout.addWidget(self.plans, stretch=1)
        split.addWidget(left)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        split.addWidget(self.view)
        split.setSizes([320, 800])
        layout.addWidget(split, stretch=1)

        self._refresh_lists()

    def _refresh_lists(self) -> None:
        self.sessions.clear()
        for session in self.controller.sessions():
            self.sessions.addItem(session["id"])
        self.plans.clear()
        for plan_id in self.controller.plans():
            self.plans.addItem(plan_id)

    def show_status(self) -> None:
        self.view.setPlainText(json.dumps(
            self.controller.resident_status(), indent=2, ensure_ascii=False))

    def run_scan(self) -> None:
        result = self.controller.resident_scan()
        self.view.setPlainText(json.dumps(result, indent=2, ensure_ascii=False))
        self._refresh_lists()

    def run_query(self) -> None:
        intent = self.query_input.text().strip()
        if not intent:
            return
        result = self.controller.resident_query(intent, category="general")
        self.view.setPlainText(json.dumps(result, indent=2, ensure_ascii=False))

    def show_session(self, item) -> None:
        events = self.controller.session_events(item.text())
        self.view.setPlainText(json.dumps(events, indent=2, ensure_ascii=False))

    def show_plan(self, item) -> None:
        records = self.controller.plan_records(item.text())
        self.view.setPlainText(json.dumps(records, indent=2, ensure_ascii=False))