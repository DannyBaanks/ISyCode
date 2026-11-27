"""Policy panel: read-only table of the real DEFAULT_RULES."""

from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                                QLabel, QPushButton, QTableWidget,
                                QTableWidgetItem, QVBoxLayout, QWidget)


class PolicyPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        hdr_row = QHBoxLayout()
        title_lbl = QLabel("POLÍTICAS DE SEGURIDAD (ISYVM DEFAULT RULES)")
        title_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #6b7385; letter-spacing: 1px;")
        hdr_row.addWidget(title_lbl)
        hdr_row.addStretch(1)

        refresh = QPushButton("Actualizar")
        refresh.setToolTip("Recargar reglas de política")
        refresh.clicked.connect(self.refresh)
        hdr_row.addWidget(refresh)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Policy: Define las políticas del sandbox y límites de ejecución (IsyVM).\n"
            "El modelo propone acciones, pero Policy decide si se permiten (ALLOW), si se deniegan (DENY)\n"
            "o si requieren verificación humana o contrato formal."
        )
        hdr_row.addWidget(self.help_button)
        layout.addLayout(hdr_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Action", "Runtime", "Allowed", "Requires verify", "Reason"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        rules = self.controller.policy_rules()
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            values = [
                rule["action"],
                rule["runtime"],
                "ALLOW" if rule["allowed"] else "DENY",
                "yes" if rule["requires_verification"] else "no",
                rule["reason"],
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))