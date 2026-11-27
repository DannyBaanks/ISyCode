"""Side drawer for the technical panels (ChatGPT-style vertical navigation).

In modern AI and IDE interfaces, secondary tooling panels live in a clean
vertical navigation sidebar like chatgpt.com instead of a crowded row of tabs.
The chat remains full height in the center, while tools, editor, terminal,
and config slide out from the side on demand.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                                QListWidgetItem, QPushButton, QSizePolicy,
                                QTabWidget, QVBoxLayout, QWidget)

from .. import theme

PANEL_ICONS = {
    "Editor": "📝",
    "Tool calls": "🛠",
    "Diff": "🔍",
    "Tests": "🧪",
    "Evidence": "📋",
    "Policy": "🛡",
    "Resident": "🧠",
    "Config": "⚙️",
    "Terminal": "💻",
    "Status": "📊",
}


class CollapsiblePanel(QObject):
    """Handle for one drawer tab."""

    toggled = Signal(bool)

    def __init__(self, title: str, content: QWidget, bar: "CollapsiblePanelBar"):
        super().__init__(bar)
        self._title = title
        self._content = content
        self._status_text = ""
        self._bar = bar

    @property
    def _expanded(self) -> bool:
        """True when this is the tab on screen and drawer is visible."""
        return self._bar.drawer_visible() and self._bar.current_panel() is self

    def set_expanded(self, expanded: bool) -> None:
        if expanded:
            self._bar.show_panel(self)
        elif self._expanded:
            self._bar.set_drawer_visible(False)

    def set_status(self, text: str) -> None:
        self._status_text = text
        self._bar.refresh_label(self)

    def status(self) -> str:
        return self._status_text

    def title(self) -> str:
        return self._title

    def content(self) -> QWidget:
        return self._content


class CollapsiblePanelBar(QWidget):
    """ChatGPT-style vertical navigation sidebar holding technical panels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: list[CollapsiblePanel] = []
        self._is_visible = False
        self._build()

    def _build(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # --- Left Column: ChatGPT-style vertical navigation list ---
        self.nav_widget = QWidget()
        self.nav_widget.setObjectName("chatgptSidebar")
        self.nav_widget.setFixedWidth(210)
        nav_layout = QVBoxLayout(self.nav_widget)
        nav_layout.setContentsMargins(8, 8, 8, 8)
        nav_layout.setSpacing(6)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 2, 2, 4)
        header_lbl = QLabel("PANELES")
        header_lbl.setObjectName("sectionTitle")
        header_layout.addWidget(header_lbl)
        header_layout.addStretch(1)

        self.hide_button = QPushButton("⇤")
        self.hide_button.setObjectName("drawerToggle")
        self.hide_button.setFixedSize(24, 24)
        self.hide_button.setToolTip("Ocultar paneles (Ctrl+` o clic)")
        self.hide_button.clicked.connect(lambda: self.set_drawer_visible(not self.drawer_visible()))
        header_layout.addWidget(self.hide_button)
        nav_layout.addWidget(header)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("chatgptNavList")
        self.nav_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.nav_list.currentRowChanged.connect(self._on_nav_row_changed)
        nav_layout.addWidget(self.nav_list, stretch=1)

        main_layout.addWidget(self.nav_widget)

        # --- Divider ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {theme.BORDER_SOFT};")
        main_layout.addWidget(sep)

        # --- Right Column: Active Panel Content ---
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()  # Top tabs hidden in favor of ChatGPT vertical list
        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.tabs, stretch=1)

        self.set_drawer_visible(False)

    # -- panels -------------------------------------------------------------

    def add_panel(self, title: str, content: QWidget, status: str = "") -> CollapsiblePanel:
        panel = CollapsiblePanel(title, content, self)
        self._panels.append(panel)
        self.tabs.addTab(content, title)
        
        icon = PANEL_ICONS.get(title, "📁")
        item = QListWidgetItem(f"{icon}  {title}")
        item.setToolTip(title)
        self.nav_list.addItem(item)

        if status:
            panel.set_status(status)
        return panel

    def panels(self) -> list[CollapsiblePanel]:
        return list(self._panels)

    def current_panel(self) -> CollapsiblePanel | None:
        index = self.tabs.currentIndex()
        if 0 <= index < len(self._panels):
            return self._panels[index]
        return None

    def show_panel(self, panel: CollapsiblePanel) -> None:
        if panel not in self._panels:
            return
        idx = self._panels.index(panel)
        previous = self.current_panel()
        self.nav_list.setCurrentRow(idx)
        self.tabs.setCurrentIndex(idx)
        self.set_drawer_visible(True)
        if previous is not None and previous is not panel:
            previous.toggled.emit(False)
        panel.toggled.emit(True)

    def label_for(self, panel: CollapsiblePanel) -> str:
        if panel.status():
            st = panel.status()
            if len(st) > 16:
                st = st[:14] + "…"
            return f"{panel.title()} · {st}"
        return panel.title()

    def refresh_label(self, panel: CollapsiblePanel) -> None:
        if panel in self._panels:
            idx = self._panels.index(panel)
            self.tabs.setTabText(idx, self.label_for(panel))
            icon = PANEL_ICONS.get(panel.title(), "📁")
            item = self.nav_list.item(idx)
            if item:
                lbl = self.label_for(panel)
                item.setText(f"{icon}  {lbl}")
                full_desc = f"{panel.title()}: {panel.status()}" if panel.status() else panel.title()
                item.setToolTip(full_desc)

    def is_reachable(self, panel: CollapsiblePanel) -> bool:
        return panel in self._panels

    # -- drawer visibility --------------------------------------------------

    def drawer_visible(self) -> bool:
        return self._is_visible

    def set_drawer_visible(self, visible: bool) -> None:
        self._is_visible = visible
        self.setVisible(visible)
        if visible:
            self.setMinimumWidth(580)
            self.setMaximumWidth(950)
            if self.nav_list.currentRow() < 0 and self.nav_list.count() > 0:
                self.nav_list.setCurrentRow(0)
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(0)
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if widget is not None:
                widget.setVisible(visible and index == self.tabs.currentIndex())
        self.hide_button.setText("⇤" if visible else "⇥")
        self.updateGeometry()

    def collapse_all(self) -> None:
        self.set_drawer_visible(False)

    # -- lending a panel to a separate window -------------------------------

    def detach(self, panel: CollapsiblePanel) -> None:
        index = self._index_of(panel)
        if index is not None:
            self.tabs.removeTab(index)
            item = self.nav_list.takeItem(index)
            del item

    def reattach(self, panel: CollapsiblePanel) -> None:
        if self._index_of(panel) is not None:
            return
        position = min(self._panels.index(panel), self.tabs.count())
        self.tabs.insertTab(position, panel.content(), self.label_for(panel))
        icon = PANEL_ICONS.get(panel.title(), "📁")
        item = QListWidgetItem(f"{icon}  {self.label_for(panel)}")
        self.nav_list.insertItem(position, item)

    def _index_of(self, panel: CollapsiblePanel) -> int | None:
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is panel.content():
                return i
        return None

    def _on_nav_row_changed(self, row: int) -> None:
        if 0 <= row < self.tabs.count():
            self.tabs.setCurrentIndex(row)

    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < len(self._panels):
            if self.nav_list.currentRow() != index:
                self.nav_list.setCurrentRow(index)
            for i, p in enumerate(self._panels):
                p.toggled.emit(i == index)
