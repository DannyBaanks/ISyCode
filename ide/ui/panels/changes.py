"""Persisted host proposals; approvals stay attached to their active turn."""

from PySide6.QtCore import Qt
from ..approval_dialog import request_decision
from ui.icons import file_icon
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)


class ChangesPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.busy_guard = lambda: False
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("CAMBIOS · PROPUESTAS DEL HOST"))
        header.addStretch()
        refresh = QPushButton("Actualizar")
        refresh.setToolTip("Recarga la lista de propuestas write/edit registradas por el host")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        self.recovery_button = QPushButton("Revisar recuperación")
        self.recovery_button.setToolTip("Prepara una recuperación segura de la propuesta seleccionada (solo cuando hay una propuesta aplicada)")
        self.recovery_button.clicked.connect(self.recover)
        header.addWidget(self.recovery_button)
        layout.addLayout(header)
        note = QLabel("Revisa y aprueba la propuesta activa en el chat. Cada aprobación corresponde a un diff y una base concreta.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Archivo", "Estado"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.currentItemChanged.connect(self._inspect)
        self.split.addWidget(self.tree)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.split.addWidget(self.details)
        layout.addWidget(self.split, 1)
        self.refresh()

    def refresh(self):
        current = self.tree.currentItem()
        selected = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        self.tree.clear()
        self.details.clear()
        try:
            records = self.controller.proposals.list()
        except (OSError, ValueError):
            self.details.setPlainText("No se pudo leer el historial de propuestas.")
            return
        for record in sorted(records, key=lambda r: r.get("created") or "", reverse=True):
            item = QTreeWidgetItem([str(record.get("path", "")), str(record.get("status", ""))])
            item.setIcon(0, file_icon(record.get("path", "")))
            item.setData(0, Qt.ItemDataRole.UserRole, record.get("id"))
            item.setToolTip(0, str(record.get("path", "")))
            self.tree.addTopLevelItem(item)
            if record.get("id") == selected:
                self.tree.setCurrentItem(item)
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        if not records:
            self.details.setPlainText("Todavía no hay propuestas. Los cambios write/edit del agente aparecerán aquí antes de aplicarse.")

    def _inspect(self, current, previous=None):
        if current is None:
            return
        try:
            record = self.controller.proposals.inspect(current.data(0, Qt.ItemDataRole.UserRole))
            text = (f"Estado: {record['status']}\nArchivo: {record['path']}\n"
                    f"Base SHA-256: {record['before_sha256'] or 'archivo nuevo'}\n\n{record['diff']}")
        except (OSError, ValueError, KeyError, TypeError):
            text = "No se pudo leer esta propuesta. El registro se conserva para revisión."
        self.details.setPlainText(text)

    def recover(self):
        current = self.tree.currentItem()
        if current is None:
            return
        if self.busy_guard():
            self.details.setPlainText("Espera a que termine el agente, comando o actualización Git antes de recuperar cambios.")
            return
        try:
            batch, retained = self.controller.proposals.prepare_recovery(current.data(0, Qt.ItemDataRole.UserRole))
        except (OSError, ValueError) as exc:
            self.details.setPlainText(str(exc))
            return
        extra = "\n\nArchivos nuevos que se conservan: " + ", ".join(retained) if retained else ""
        answer = request_decision(self, "recovery", {"paths": [change.path for change in batch.changes]}, batch.diff + extra)
        if answer is not True:
            self.controller.proposals.reject_batch(batch)
            self.refresh()
            return
        result = self.controller.tool_execution.apply_host_batch(batch, operator_approved=True, mode=self.controller.mode())
        self.refresh()
        self.details.appendPlainText("\nRecuperación aplicada." if result.success else "\n" + result.stderr)
