"""Conversation selection; technical resident sessions are shown elsewhere."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget


class ConversationsPanel(QWidget):
    session_selected = Signal(str)
    new_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel("Conversaciones")
        title.setObjectName("githubSectionTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        button = QPushButton("Nueva conversación")
        button.setProperty("variant", "primary")
        button.clicked.connect(self.new_requested.emit)
        layout.addWidget(button)
        self.list_widget = QListWidget()
        self.list_widget.itemActivated.connect(lambda item: self.session_selected.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list_widget.itemClicked.connect(lambda item: self.session_selected.emit(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.list_widget, 1)
        self.hint = QLabel("El historial se guarda en el proyecto. Las sesiones técnicas del residente son independientes.")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("repoMetadata")
        layout.addWidget(self.hint)
        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        for session in self.controller.conversations.list():
            item = QListWidgetItem(session["title"] + "\n" + session["updated"][:16].replace("T", " "))
            item.setData(Qt.ItemDataRole.UserRole, session["id"])
            item.setToolTip(session["provider"] + " · " + session["model"])
            self.list_widget.addItem(item)
