"""Concrete host review for commands and prepared file changes."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QPlainTextEdit, QVBoxLayout)


def request_decision(parent, tool_name, arguments, diff):
    dialog = QDialog(parent)
    command = arguments.get("approval_kind") == "command"
    dialog.setWindowTitle("Revisar comando" if command else "Revisar cambios")
    dialog.resize(860, 650)
    layout = QVBoxLayout(dialog)
    title = QLabel("Comando aislado · decisión exacta" if command else
                   f"Cambios preparados · {len(arguments.get('paths', [])) or 1} archivos")
    title.setObjectName("pageTitle")
    title.setTextFormat(Qt.TextFormat.PlainText)
    title.setWordWrap(True)
    layout.addWidget(title)
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setObjectName("monoView")
    view.setPlainText(diff)
    layout.addWidget(view, 1)
    note = QLabel("El permiso permanente se puede revocar en Ajustes y conserva solo este comando exacto. Los cambios de archivos se revisan después." if command else
                  "Aplicar comprueba las bases SHA-256 otra vez. Un fallo parcial conserva el journal y permite preparar recuperación.")
    note.setWordWrap(True)
    layout.addWidget(note)
    buttons = QDialogButtonBox()
    result = False
    def choose(value):
        nonlocal result
        result = value
        dialog.accept()
    reject = buttons.addButton("Rechazar", QDialogButtonBox.ButtonRole.RejectRole)
    reject.setDefault(True)
    reject.clicked.connect(dialog.reject)
    approve = buttons.addButton("Permitir una vez" if command else "Aplicar cambios revisados", QDialogButtonBox.ButtonRole.ActionRole)
    approve.clicked.connect(lambda: choose(True))
    if command:
        always = buttons.addButton("Permitir siempre este comando", QDialogButtonBox.ButtonRole.ActionRole)
        always.clicked.connect(lambda: choose("always"))
    layout.addWidget(buttons)
    dialog.exec()
    return result
