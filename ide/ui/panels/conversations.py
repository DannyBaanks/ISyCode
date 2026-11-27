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
        self._current: str | None = None
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("conversationList")
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list_widget.setSpacing(2)
        self.list_widget.itemActivated.connect(lambda item: self.session_selected.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list_widget.itemClicked.connect(lambda item: self.session_selected.emit(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.list_widget, 1)
        self.hint = QLabel("El historial se guarda en el proyecto. Las sesiones técnicas del residente son independientes.")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("repoMetadata")
        layout.addWidget(self.hint)
        self.refresh()

    def set_current(self, session_id: str | None) -> None:
        """Mark the open conversation so the list shows where the user is."""
        self._current = session_id
        self.list_widget.clearSelection()
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if session_id and item.data(Qt.ItemDataRole.UserRole) == session_id:
                self.list_widget.setCurrentItem(item)
                return
        self.list_widget.setCurrentRow(-1)

    def refresh(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for session in self.controller.conversations.list():
            title = (session["title"] or "Sin título").strip()
            item = QListWidgetItem(title + "\n" + session["updated"][:16].replace("T", " "))
            item.setData(Qt.ItemDataRole.UserRole, session["id"])
            item.setToolTip(title + "\n" + session["provider"] + " · " + session["model"])
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self.set_current(self._current)
