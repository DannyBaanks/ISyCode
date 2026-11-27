"""Quick-open palette: fuzzy file finder + ``>`` command mode (Orca-inspired).

Two modes share one line edit:

* **Files** (default) — bounded ``os.scandir`` walk of ``root_dir`` (skips
  ``.git``, ``.venv``, ``node_modules`` and other vendored caches; hard cap of
  15 000 entries), ranked by :func:`core.fuzzy.rank_candidates`.
* **Commands** — typing ``>`` switches to the registered actions, fuzzy-ranked
  on their title.

Keyboard: Up/Down move, Enter activates the current row, Esc closes. The
dialog never follows symlinks or leaves ``root_dir``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, QSize
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                                QPushButton, QVBoxLayout, QWidget)

from core.fuzzy import matched_ranges, rank_candidates
from ui.icons import file_icon, icon

MAX_ENTRIES = 15_000
SKIP_DIRS = frozenset({".git", ".venv", "venv", ".venv_linux", "node_modules", "__pycache__",
                       ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "dist", "build",
                       ".tox", ".idea", ".vscode-server"})
RESULT_LIMIT = 200


@dataclass(frozen=True)
class Command:
    """A palette action. ``title`` is fuzzy-matched; ``keywords`` widen matching."""

    id: str
    title: str
    run: Callable[[], None]
    keywords: str = ""

    @property
    def match_text(self) -> str:
        return f"{self.title} {self.keywords}".strip()


def _highlight(item: QListWidgetItem, text: str, ranges: list[tuple[int, int]]) -> None:
    """Store escaped rich-text highlight metadata without polluting plain item text."""
    if not ranges:
        return
    from html import escape
    pieces: list[str] = []
    cursor = 0
    for start, end in ranges:
        pieces.append(escape(text[cursor:start]))
        pieces.append("<b>" + escape(text[start:end]) + "</b>")
        cursor = end
    pieces.append(escape(text[cursor:]))
    item.setData(Qt.ItemDataRole.UserRole + 2, "".join(pieces))


class QuickOpenDialog(QDialog):
    """Modal-ish, non-blocking palette. Emits ``file_selected``/``command_selected``."""

    file_selected = Signal(str)
    command_selected = Signal(str)

    def __init__(self, root_dir: str | Path, on_open_file: Callable[[str], None] | None = None,
                 actions: Iterable[Command | tuple] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowTitle("Abrir rápido")
        self.setMinimumWidth(720)
        self.setMaximumHeight(600)
        self.root_dir = Path(root_dir).resolve()
        self._on_open_file = on_open_file
        self._files: list[str] = []
        self._scan_partial = False
        self._commands: list[Command] = [a if isinstance(a, Command) else Command(*a) for a in (actions or [])]
        self._mode = "files"
        self._current_results: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe para buscar archivos…  (> para comandos)")
        self.input.setObjectName("paletteInput")
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(self._on_text_changed)
        self.input.installEventFilter(self)
        layout.addWidget(self.input)

        self.results = QListWidget()
        self.results.setObjectName("paletteResults")
        self.results.setIconSize(QSize(20, 20))
        self.results.setUniformItemSizes(True)
        self.results.setCurrentRow(0)
        self.results.itemActivated.connect(self._activate_item)
        self.results.itemClicked.connect(lambda item: self.results.setCurrentItem(item))
        layout.addWidget(self.results, stretch=1)

        footer = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("repoMetadata")
        footer.addWidget(self.status)
        footer.addStretch(1)
        hint = QLabel("↑↓ mover · Enter abrir · Esc cerrar")
        hint.setObjectName("repoMetadata")
        footer.addWidget(hint)
        layout.addLayout(footer)

        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(8)
        self._scan_timer.timeout.connect(self._scan_batch)
        self._scan_stack: list[Path] = []
        self._scan_iter: os.ScandirIterator | None = None
        self._scan_visited = 0
        self._scan_started = 0.0
        self._start_scan()

        self.file_selected.connect(self._handle_file_selected)
        self.command_selected.connect(self._handle_command_selected)
        self._refresh()

    # --- scanning -------------------------------------------------------------

    def _start_scan(self) -> None:
        self._files = []
        self._scan_stack = [self.root_dir] if self.root_dir.is_dir() else []
        self._scan_iter = None
        self._scan_visited = 0
        self._scan_partial = False
        if self._scan_stack:
            self._scan_timer.start()
        else:
            self._finish_scan()

    def _scan_batch(self) -> None:
        """Walk the tree in small event-loop friendly slices (never blocks typing)."""
        import time
        budget = 0.012
        started = time.monotonic()
        while time.monotonic() - started < budget:
            if len(self._files) >= MAX_ENTRIES:
                self._scan_partial = True
                self._finish_scan()
                return
            if self._scan_iter is None:
                if not self._scan_stack:
                    self._finish_scan()
                    return
                try:
                    self._scan_iter = os.scandir(self._scan_stack.pop())
                except OSError:
                    self._scan_partial = True
                    continue
            try:
                entry = next(self._scan_iter)
            except StopIteration:
                self._scan_iter.close()
                self._scan_iter = None
                continue
            except OSError:
                self._scan_partial = True
                continue
            self._scan_visited += 1
            if self._scan_visited > MAX_ENTRIES * 4:
                self._scan_partial = True
                self._finish_scan()
                return
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIP_DIRS:
                        continue
                    self._scan_stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    try:
                        relative = Path(entry.path).relative_to(self.root_dir).as_posix()
                    except ValueError:
                        continue
                    self._files.append(relative)
            except OSError:
                self._scan_partial = True
        # Results list refresh is throttled: typing triggers its own refresh, scanning
        # only refreshes when the user has not typed in a while or the scan finishes.
        if self._mode == "files" and self._scan_stack and len(self._files) % 500 < 50:
            self._refresh()

    def _finish_scan(self) -> None:
        self._scan_timer.stop()
        self._scan_iter = None
        self._scan_stack = []
        self._refresh()

    def file_count(self) -> int:
        return len(self._files)

    # --- mode & ranking ---------------------------------------------------------

    def _mode_for(self, text: str) -> str:
        return "commands" if text.startswith(">") else "files"

    def _query(self, text: str) -> str:
        return text[1:].strip() if text.startswith(">") else text.strip()

    def _on_text_changed(self, text: str) -> None:
        self._refresh()

    def _refresh(self) -> None:
        text = self.input.text()
        self._mode = self._mode_for(text)
        query = self._query(text)
        selected = self.results.currentRow()
        self.results.setUpdatesEnabled(False)
        self.results.clear()
        if self._mode == "commands":
            ranked = rank_candidates(query, self._commands, key=lambda c: c.match_text)
            for command in ranked[:RESULT_LIMIT]:
                item = QListWidgetItem(icon("code", size=20), command.title)
                item.setData(Qt.ItemDataRole.UserRole, command.id)
                item.setToolTip(command.title)
                _highlight(item, command.title, matched_ranges(query, command.title))
                self.results.addItem(item)
            self._current_results = [c.id for c in ranked[:RESULT_LIMIT]]
            self.status.setText(f"{len(ranked)} comando(s)")
        else:
            candidates = self._files if query else self._recent_first()
            ranked = rank_candidates(query, candidates)[:RESULT_LIMIT]
            for relative in ranked:
                item = QListWidgetItem(file_icon(str(self.root_dir / relative)), relative)
                item.setData(Qt.ItemDataRole.UserRole, relative)
                item.setToolTip(str(self.root_dir / relative))
                _highlight(item, relative, matched_ranges(query, relative))
                self.results.addItem(item)
            self._current_results = list(ranked)
            total = len(self._files)
            suffix = " · muestra acotada" if self._scan_partial else ""
            scanning = " · escaneando…" if self._scan_timer.isActive() else ""
            self.status.setText(f"{total} archivo(s){scanning}{suffix}")
        self.results.setUpdatesEnabled(True)
        if self.results.count():
            self.results.setCurrentRow(min(max(selected, 0), self.results.count() - 1))

    def _recent_first(self) -> list[str]:
        """Shallow paths first when the query is empty, so the root files show on top."""
        return sorted(self._files, key=lambda p: (p.count("/"), len(p), p))

    # --- keyboard ---------------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                self._move(key)
                return True
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                self._activate_current()
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def _move(self, key: int) -> None:
        count = self.results.count()
        if not count:
            return
        row = self.results.currentRow()
        if key == Qt.Key.Key_Down:
            row = (row + 1) % count
        elif key == Qt.Key.Key_Up:
            row = (row - 1) % count
        elif key == Qt.Key.Key_PageDown:
            row = min(count - 1, row + 10)
        elif key == Qt.Key.Key_PageUp:
            row = max(0, row - 10)
        self.results.setCurrentRow(row)
        self.results.scrollToItem(self.results.item(row))

    def _activate_current(self) -> None:
        item = self.results.currentItem()
        if item is not None:
            self._activate_item(item)

    def _activate_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if self._mode == "commands":
            self.command_selected.emit(str(data))
        else:
            self.file_selected.emit(str(self.root_dir / str(data)))

    def _handle_file_selected(self, path: str) -> None:
        if self._on_open_file is not None:
            self._on_open_file(path)
        self.accept()

    def _handle_command_selected(self, command_id: str) -> None:
        command = next((c for c in self._commands if c.id == command_id), None)
        if command is not None:
            try:
                command.run()
            finally:
                self.accept()
        else:
            self.reject()

    def add_action(self, command: Command | tuple) -> None:
        cmd = command if isinstance(command, Command) else Command(*command)
        self._commands.append(cmd)
        self._refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.input.setFocus()
        self.input.selectAll()


__all__ = ["Command", "QuickOpenDialog", "MAX_ENTRIES", "SKIP_DIRS"]
