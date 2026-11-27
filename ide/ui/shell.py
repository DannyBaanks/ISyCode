"""Approved native layout: one chat/editor, persistent rail and full pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QSplitter,
                               QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from .icons import icon
from .panels.collapsible import CollapsiblePanel


NAVIGATION = [
    ("Conversaciones", "Conversación", "chat"), ("Editor", "Archivos", "code"),
    ("Cambios", "Cambios", "changes"), ("Tool calls", "Herramientas", "tools"),
    ("Tests", "Pruebas", "tests"), ("Evidence", "Evidencia", "evidence"),
    ("Status", "Sistema", "system"), ("GitHub", "GitHub", "github"),
    ("Config", "Providers", "provider"), ("Ajustes", "Ajustes", "settings"),
    ("Terminal", "Terminal", "terminal"),
]


class DesktopShell(QWidget):
    view_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels = []
        self._by_title = {}
        self._locations = {}
        self._lent = set()
        self._current = None
        self._ready = False
        self._nav_visible = True
        self.view = "conversation"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.navigation = QFrame()
        self.navigation.setObjectName("ideNavigation")
        self.navigation.setFixedWidth(184)
        nav = QVBoxLayout(self.navigation)
        nav.setContentsMargins(8, 18, 8, 14)
        nav.setSpacing(8)
        self.nav_buttons = {}
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for title, label, symbol in NAVIGATION:
            button = QPushButton(label)
            button.setObjectName("ideNavigationItem")
            button.setIcon(icon(symbol))
            button.setIconSize(QSize(24, 24))
            button.setCheckable(True)
            button.setToolTip(label)
            button.clicked.connect(lambda checked=False, t=title: self.show_title(t))
            self.nav_group.addButton(button)
            self.nav_buttons[title] = button
            nav.addWidget(button)
            if title == "GitHub":
                nav.addStretch(1)
        nav.addStretch(1)
        layout.addWidget(self.navigation)
        self.pages = QStackedWidget()
        self.pages.setObjectName("idePages")
        layout.addWidget(self.pages, 1)

    def add_panel(self, title, content, status=""):
        panel = CollapsiblePanel(title, content, self)
        self._panels.append(panel)
        self._by_title[title] = panel
        self.pages.addWidget(content)
        self._locations[title] = ("page", None)
        if status:
            panel.set_status(status)
        return panel

    def build_workspace(self, chat, workspace, conversations, editor, changes, diff, *, title="Conversación"):
        self.chat = chat
        self.workspace = workspace
        self.conversations = conversations
        self.editor = editor
        self.work_page = QWidget()
        self.work_page.setObjectName("ideWorkPage")
        whole = QVBoxLayout(self.work_page)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(18, 10, 18, 10)
        self.conversation_title = QLabel(title)
        self.conversation_title.setObjectName("conversationTitle")
        self.conversation_title.setTextFormat(Qt.TextFormat.PlainText)
        self.conversation_title.setWordWrap(True)
        self.conversation_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.conversation_title, 1)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.conversation_button = QPushButton("Conversación")
        self.code_button = QPushButton("Código + chat")
        for button, view in ((self.conversation_button, "conversation"), (self.code_button, "code")):
            button.setCheckable(True)
            button.setObjectName("viewSwitch")
            button.clicked.connect(lambda checked=False, v=view: self.set_view(v))
            group.addButton(button)
            top.addWidget(button)
        whole.addLayout(top)
        self.columns = QSplitter(Qt.Orientation.Horizontal)
        self.columns.setChildrenCollapsible(False)
        self.project_rail = QSplitter(Qt.Orientation.Vertical)
        self.project_rail.setObjectName("projectRail")
        self.project_rail.setMinimumWidth(170)
        self.project_rail.setMaximumWidth(340)
        workspace.setMinimumWidth(150)
        workspace.setMaximumWidth(16777215)
        self.project_rail.addWidget(workspace)
        self.pages.removeWidget(conversations)
        self.project_rail.addWidget(conversations)
        conversations.show()  # removeWidget preserves the stacked page's hidden flag.
        self._locations["Conversaciones"] = ("rail", self.project_rail)
        self.project_rail.setSizes([460, 350])
        self.columns.addWidget(self.project_rail)
        self.work_split = QSplitter(Qt.Orientation.Horizontal)
        self.work_split.setChildrenCollapsible(False)
        chat.setMinimumWidth(300)
        self.work_split.addWidget(chat)
        self.inspector = QTabWidget()
        self.inspector.setObjectName("ideInspector")
        self.inspector.setDocumentMode(True)
        self.inspector.setMinimumWidth(280)
        self.inspector.tabBar().setExpanding(False)
        for panel_title, content, label in (("Editor", editor, "Editor"), ("Cambios", changes, "Cambios"), ("Diff", diff, "Diff")):
            self.pages.removeWidget(content)
            self.inspector.addTab(content, label)
            self._locations[panel_title] = ("inspector", self.inspector)
        self.work_split.addWidget(self.inspector)
        self.columns.addWidget(self.work_split)
        self.columns.setStretchFactor(0, 0)
        self.columns.setStretchFactor(1, 1)
        self.columns.setSizes([250, 1050])
        whole.addWidget(self.columns, 1)
        self.pages.addWidget(self.work_page)
        self._ready = True
        self.set_view("conversation", notify=False)
        self.show_title("Conversaciones")

    def set_view(self, view, *, notify=True):
        if not self._ready or view not in {"conversation", "code"}:
            return
        self.view = view
        self.pages.setCurrentWidget(self.work_page)
        self.nav_buttons["Conversaciones" if view == "conversation" else "Editor"].setChecked(True)
        self.conversation_button.setChecked(view == "conversation")
        self.code_button.setChecked(view == "code")
        self.chat.setMaximumWidth(500 if view == "code" else 16777215)
        self.chat.set_compact(view == "code")
        self.work_split.insertWidget(0, self.inspector if view == "code" else self.chat)
        # An unopened editor is not a useful inspector for a conversation.
        self.inspector.setVisible(view == "code" or self.editor.current_path is not None)
        self.workspace.show()
        self.conversations.setVisible(view == "conversation")
        self.project_rail.setSizes([300, 600] if view == "conversation" else [900, 0])
        self.work_split.setSizes([800, 500] if view == "code" else [760, 490])
        if notify:
            self.view_changed.emit(view)

    def show_title(self, title):
        panel = self._by_title.get(title)
        if panel is not None:
            self.show_panel(panel)

    def show_panel(self, panel):
        title = panel.title()
        if title in self._lent:
            # MainWindow opens the already lent widget's window through its menu.
            return
        previous = self._current
        self._current = panel
        location = self._locations[title][0]
        if self._ready and title in {"Conversaciones", "Editor"}:
            self.set_view("conversation" if title == "Conversaciones" else "code")
            if title == "Editor":
                self.inspector.setCurrentWidget(panel.content())
        elif location == "group":
            tabs = self._locations[title][1]
            self.pages.setCurrentWidget(tabs)
            tabs.setCurrentWidget(panel.content())
        elif self._ready and location in {"rail", "inspector"}:
            self.pages.setCurrentWidget(self.work_page)
            if location == "inspector":
                self.inspector.show()
                self.inspector.setCurrentWidget(panel.content())
            else:
                self.project_rail.show()
        else:
            self.pages.setCurrentWidget(self._locations[title][1] or panel.content())
            panel.content().show()
            if title == "Terminal" and hasattr(panel.content(), "ensure_started"):
                panel.content().ensure_started()
            elif title == "Evidence" and hasattr(panel.content(), "refresh_receipts"):
                panel.content().refresh_receipts()
            elif title == "Tests" and hasattr(panel.content(), "refresh_discovery"):
                panel.content().refresh_discovery()
        if title in self.nav_buttons:
            self.nav_buttons[title].setChecked(True)
        elif location == "group":
            self.nav_buttons["Status"].setChecked(True)
        if previous and previous is not panel:
            previous.toggled.emit(False)
        panel.toggled.emit(True)

    def group_pages(self, entries):
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        for title, label in entries:
            panel = self._by_title[title]
            self.pages.removeWidget(panel.content())
            tabs.addTab(panel.content(), label)
            self._locations[title] = ("group", tabs)
        self.pages.addWidget(tabs)

    def panels(self):
        return list(self._panels)

    def finish_pages(self):
        """Give technical pages consistent, spacious native headers."""
        captions = {"Tool calls": ("Herramientas", "Catálogo real y llamadas del agente"),
                    "Tests": ("Pruebas", "Resultados y salida del proyecto"),
                    "Evidence": ("Evidencia", "Recibos y resultados disponibles"),
                    "Terminal": ("Terminal manual", "Tu terminal del host; el agente usa otro runtime")}
        for title, (caption, subtitle) in captions.items():
            panel = self._by_title[title]
            self.pages.removeWidget(panel.content())
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(22, 20, 22, 20)
            heading = QLabel(caption)
            heading.setObjectName("pageTitle")
            layout.addWidget(heading)
            description = QLabel(subtitle)
            description.setObjectName("pageSubtitle")
            description.setWordWrap(True)
            layout.addWidget(description)
            layout.addWidget(panel.content(), 1)
            panel.content().show()  # removeWidget preserves the stacked page's hidden flag.
            self.pages.addWidget(page)
            self._locations[title] = ("page", page)

    def current_panel(self):
        return self._current

    def drawer_visible(self):
        return self._nav_visible

    def set_drawer_visible(self, visible):
        self._nav_visible = bool(visible)
        self.navigation.setVisible(visible)

    def collapse_all(self):
        self.set_drawer_visible(False)

    def label_for(self, panel):
        return panel.title() + (" · " + panel.status() if panel.status() else "")

    def refresh_label(self, panel):
        button = self.nav_buttons.get(panel.title())
        if button:
            button.setToolTip(self.label_for(panel))

    def is_reachable(self, panel):
        return panel in self._panels

    def detach(self, panel):
        title = panel.title()
        kind, container = self._locations[title]
        if kind == "page":
            if container is not None:
                container.layout().removeWidget(panel.content())
            else:
                self.pages.removeWidget(panel.content())
        elif kind in {"inspector", "group"}:
            container.removeTab(container.indexOf(panel.content()))
        self._lent.add(title)
        button = self.nav_buttons.get(title)
        if button:
            button.setEnabled(False)

    def reattach(self, panel):
        title = panel.title()
        if title not in self._lent:
            return
        kind, container = self._locations[title]
        if kind == "page":
            if container is not None:
                container.layout().addWidget(panel.content())
            else:
                self.pages.addWidget(panel.content())
        elif kind in {"inspector", "group"}:
            container.addTab(panel.content(), title)
        elif kind == "rail":
            self.project_rail.addWidget(panel.content())
        self._lent.remove(title)
        button = self.nav_buttons.get(title)
        if button:
            button.setEnabled(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 1100
        width = 58 if compact else 166
        if self.navigation.width() != width:
            self.navigation.setFixedWidth(width)
            for title, label, symbol in NAVIGATION:
                self.nav_buttons[title].setText("" if compact else label)
