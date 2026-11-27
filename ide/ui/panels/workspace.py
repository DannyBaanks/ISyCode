"""Workspace panel: file tree + search (visualization only)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import (QDir, QFileSystemWatcher, QModelIndex, QSortFilterProxyModel, QSize, Qt, Signal,
                               QTimer)
from PySide6.QtWidgets import QFileSystemModel, QHeaderView
from ui.icons import file_icon, icon
from core.project_tree import visible_name
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                                QListWidgetItem, QPushButton, QStyledItemDelegate, QTreeView, QVBoxLayout,
                                QWidget)

class _IconFileSystemModel(QFileSystemModel):
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0 and index.isValid():
            return file_icon(self.filePath(index), self.isDir(index))
        return super().data(index, role)


class _ExcludeFilter(QSortFilterProxyModel):
    """Hides excluded directories from the filesystem model."""

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        index = self.sourceModel().index(source_row, 0, source_parent)
        name = index.data(Qt.ItemDataRole.DisplayRole)
        path = self.sourceModel().filePath(index)
        root = getattr(self, "_root", None)
        if root is not None and root.is_relative_to(Path(path)):
            return True
        return bool(name and visible_name(name) and not Path(path).is_symlink())


class _EllipsisDelegate(QStyledItemDelegate):
    """Delegate that adds tooltip with full name and handles ellipsis."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Ensure text is not elided in the view - we handle via tooltip
        option.textElideMode = Qt.TextElideMode.ElideRight


class WorkspacePanel(QWidget):
    file_open = Signal(str)
    hide_requested = Signal()
    #: Emitted (debounced) when the active workspace's ``.git/HEAD`` or ``.git/index``
    #: changes, so callers can refresh branch/dirty indicators without polling.
    git_state_changed = Signal()

    GIT_WATCH_DEBOUNCE_MS = 250

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root: Path | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Proyecto")
        lbl.setObjectName("githubSectionTitle")
        hdr_row.addWidget(lbl)
        self.git_label = QLabel("")
        self.git_label.setObjectName("repoMetadata")
        hdr_row.addWidget(self.git_label)
        hdr_row.addStretch(1)

        self.minimize_btn = QPushButton()
        self.minimize_btn.setIcon(icon("menu", size=18))
        self.minimize_btn.setIconSize(QSize(18, 18))
        self.minimize_btn.setObjectName("workspaceMinimize")
        self.minimize_btn.setFixedSize(28, 28)
        self.minimize_btn.setStyleSheet("padding: 0; min-height: 0; min-width: 0;")
        self.minimize_btn.setToolTip("Minimizar carpetas (Ctrl+B)")
        self.minimize_btn.clicked.connect(self.hide_requested.emit)
        hdr_row.addWidget(self.minimize_btn)
        layout.addLayout(hdr_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar archivos…")
        self.search.textChanged.connect(self._search)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.setVisible(False)
        self.results.itemDoubleClicked.connect(self._open_result)
        self.search_status = QLabel()
        self.search_status.setObjectName("repoMetadata")
        self.search_status.setWordWrap(True)
        self.search_status.hide()
        layout.addWidget(self.search_status)
        layout.addWidget(self.results, stretch=1)

        self.tree = QTreeView()
        self.tree.setIconSize(QSize(22, 22))
        self.results.setIconSize(QSize(22, 22))
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setItemDelegate(_EllipsisDelegate(self.tree))
        self.tree.setMouseTracking(True)
        self.tree.entered.connect(self._on_entered)
        self.tree.doubleClicked.connect(self._open_tree_index)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setIndentation(16)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.setStyleSheet("""
            QTreeView {
                border: none;
                background: transparent;
                outline: none;
            }
            QTreeView::item {
                padding: 2px 4px;
                border-radius: 3px;
            }
            QTreeView::item:hover {
                background: #182433;
            }
            QTreeView::item:selected {
                background: #0d3043;
                color: #e8f1fa;
            }
            QTreeView::branch {
                background: transparent;
            }
        """)
        layout.addWidget(self.tree, stretch=1)
        self._search_scan = None
        self._search_stack = []
        self._search_timer = QTimer(self)
        self._search_timer.setInterval(10)
        self._search_timer.timeout.connect(self._search_batch)
        # Non-blocking Git state watcher (QFileSystemWatcher is event-driven; no subprocess,
        # no polling thread). Only active while the workspace is inside a Git repository.
        self._git_watcher: QFileSystemWatcher | None = None
        self._git_watch_paths: list[str] = []
        self._git_debounce = QTimer(self)
        self._git_debounce.setSingleShot(True)
        self._git_debounce.setInterval(self.GIT_WATCH_DEBOUNCE_MS)
        self._git_debounce.timeout.connect(self.git_state_changed.emit)

    def set_root(self, root: str | Path) -> None:
        self._stop_search()
        self._root = Path(root).resolve()
        model = self._fs_model(self._root)
        self.tree.setModel(model)
        self.tree.setRootIndex(model.mapFromSource(
            model.sourceModel().index(str(self._root))))
        self.tree.expandToDepth(1)
        # Set column width to accommodate longer names
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.watch_git_state()
        self.refresh_git_status()
        self._search(self.search.text())

    # --- git state watcher -------------------------------------------

    def _git_dir(self) -> Path | None:
        """The ``.git`` directory for the workspace, following a linked-worktree ``gitdir:`` file."""
        if self._root is None:
            return None
        dot = self._root / ".git"
        try:
            if dot.is_dir():
                return dot
            if dot.is_file():
                # Linked worktree: ".git" is a file like "gitdir: /repo/.git/worktrees/name".
                text = dot.read_text(encoding="utf-8", errors="replace").strip()
                if text.startswith("gitdir:"):
                    target = Path(text[len("gitdir:"):].strip())
                    return target if target.is_absolute() else (self._root / target)
        except OSError:
            return None
        return None

    def watch_git_state(self) -> None:
        """Arm ``.git/HEAD`` and ``.git/index`` watchers; no-op when the workspace is not a repo."""
        self.stop_watching_git()
        git_dir = self._git_dir()
        if git_dir is None:
            return
        paths = [str(git_dir / name) for name in ("HEAD", "index") if (git_dir / name).exists()]
        if not paths:
            return
        watcher = QFileSystemWatcher(self)
        # NOTE: ``addPaths`` returns the paths that *failed* to be added (empty on success),
        # so consult ``files()`` afterwards instead of treating an empty return as failure.
        failed = watcher.addPaths(paths)
        watched_files = [p for p in paths if p not in failed and p in watcher.files()]
        if not watched_files:
            watcher.deleteLater()
            return
        # Git replaces HEAD/index atomically (rename), which drops the inode watch;
        # watching the containing directory too keeps the signal reliable and lets us re-arm.
        for directory in {str(git_dir), *(str(Path(p).parent) for p in watched_files)}:
            watcher.addPath(directory)
        watcher.directoryChanged.connect(self._on_git_dir_changed)
        watcher.fileChanged.connect(self._schedule_git_state_changed)
        self._git_watcher = watcher
        self._git_watch_paths = watched_files

    def stop_watching_git(self) -> None:
        if self._git_watcher is not None:
            try:
                self._git_watcher.fileChanged.disconnect(self._schedule_git_state_changed)
            except RuntimeError:
                pass
            try:
                self._git_watcher.directoryChanged.disconnect(self._on_git_dir_changed)
            except RuntimeError:
                pass
            paths = self._git_watcher.files() + self._git_watcher.directories()
            if paths:
                self._git_watcher.removePaths(paths)
            self._git_watcher.deleteLater()
            self._git_watcher = None
        self._git_watch_paths = []
        self._git_debounce.stop()

    def git_watched_paths(self) -> list[str]:
        """Files currently watched (for diagnostics/tests)."""
        return list(self._git_watch_paths)

    def _on_git_dir_changed(self, _path: str) -> None:
        # A directory change means HEAD/index may have been replaced; re-arm and notify.
        self.watch_git_state()
        self._schedule_git_state_changed()

    def _schedule_git_state_changed(self, _path: str = "") -> None:
        self._git_debounce.start()  # restarts the 250 ms window on every burst of events

    # --- filesystem model ---------------------------------------------

    def _fs_model(self, root: Path):
        source = _IconFileSystemModel(self)
        source.setRootPath(str(root))
        source.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        proxy = _ExcludeFilter(self)
        proxy._root = root.resolve()
        proxy.setSourceModel(source)
        return proxy

    def _on_entered(self, index: QModelIndex) -> None:
        """Show tooltip with full name when hovering."""
        if not index.isValid():
            return
        proxy = index.model()
        source = proxy.mapToSource(index)
        path = proxy.sourceModel().filePath(source)
        name = Path(path).name
        self.tree.setToolTip(name)

    # --- search -------------------------------------------------------

    def _search(self, text: str) -> None:
        self._stop_search()
        if not text.strip():
            self.search_status.hide()
            self.results.setVisible(False)
            self.tree.setVisible(True)
            return
        self.results.clear()
        if self._root is None:
            return
        self._search_text = text.casefold()
        self._search_stack = [self._root]
        self._search_visited = 0
        self._search_started = time.monotonic()
        self._search_partial = False
        self.search_status.setText("Buscando en el proyecto…")
        self.search_status.show()
        self.results.setVisible(True)
        self.tree.setVisible(False)
        self._search_batch()
        if self._search_stack or self._search_scan is not None:
            self._search_timer.start()

    def _stop_search(self) -> None:
        if hasattr(self, "_search_timer"):
            self._search_timer.stop()
        if getattr(self, "_search_scan", None) is not None:
            self._search_scan.close()
        self._search_scan = None
        self._search_stack = []

    def _finish_search(self, limited=False) -> None:
        self._stop_search()
        partial = limited or self._search_partial
        self.search_status.setText(f"{self.results.count()} coincidencias" + (" · muestra acotada; precisa la búsqueda" if partial else ""))

    def _search_batch(self) -> None:
        # Small native event-loop batches: typing and closing the app never wait
        # for a recursive filesystem inventory.
        for _ in range(64):
            if self.results.count() >= 100 or self._search_visited >= 20_000 or time.monotonic() - self._search_started > 5:
                self._finish_search(limited=True)
                return
            if self._search_scan is None:
                if not self._search_stack:
                    self._finish_search()
                    return
                try:
                    self._search_scan = os.scandir(self._search_stack.pop())
                except OSError:
                    self._search_partial = True
                    continue
            try:
                entry = next(self._search_scan)
            except StopIteration:
                self._search_scan.close()
                self._search_scan = None
                continue
            except OSError:
                self._search_scan.close()
                self._search_scan = None
                self._search_partial = True
                continue
            self._search_visited += 1
            if not visible_name(entry.name) or entry.is_symlink():
                continue
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    self._search_stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    relative = path.relative_to(self._root).as_posix()
                    if self._search_text in relative.casefold():
                        self.results.addItem(QListWidgetItem(file_icon(path), relative))
            except OSError:
                self._search_partial = True

    def _open_result(self, item: QListWidgetItem) -> None:
        if self._root is not None:
            self.file_open.emit(str(self._root / item.text()))

    def _open_tree_index(self, index: QModelIndex) -> None:
        proxy = self.tree.model()
        source_index = proxy.mapToSource(index)
        path = source_index.model().filePath(source_index)
        if Path(path).is_file():
            self.file_open.emit(path)

    def _show_context_menu(self, position) -> None:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QMenu
        index = self.tree.indexAt(position)
        if not index.isValid():
            return
        proxy = self.tree.model()
        source_index = proxy.mapToSource(index)
        path_str = source_index.model().filePath(source_index)
        path = Path(path_str)

        menu = QMenu(self)
        if path.is_file():
            open_act = menu.addAction("Abrir en editor")
            open_act.triggered.connect(lambda: self.file_open.emit(path_str))

        if self._root is not None:
            try:
                rel = str(path.relative_to(self._root)).replace("\\", "/")
                copy_act = menu.addAction(f"Copiar ruta relativa ({rel})")
                copy_act.triggered.connect(lambda: QGuiApplication.clipboard().setText(rel))
            except ValueError:
                pass

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def refresh_git_status(self) -> None:
        """GitHub owns repository inspection; never run repository hooks on load."""
        self.git_label.setText("Git · sin comprobar")
        self.git_label.setToolTip("Abre GitHub para comprobar commits y cambios locales. Sin comprobar no significa limpio.")
