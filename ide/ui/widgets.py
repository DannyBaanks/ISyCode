"""Small shared UI helpers so every panel follows the same layout rules.

Rules (UI/UX audit 2026-11-27):
- Buttons size to their text; primary action on the right, never full width.
- Commands are shown as shell strings in monospace, never as Python/JSON lists.
- Destructive or item-scoped actions are disabled until something is selected.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Iterable

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QWidget


def button_row(*widgets: QWidget, align: str = "right", spacing: int = 8) -> QHBoxLayout:
    """Return a horizontal row of compact buttons aligned left or right."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(spacing)
    if align == "right":
        row.addStretch(1)
    for widget in widgets:
        row.addWidget(widget)
    if align != "right":
        row.addStretch(1)
    return row


def format_command(value: Any) -> str:
    """Render argv-like values (list, JSON list string, plain string) as one shell line."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                try:
                    import ast
                    parsed = ast.literal_eval(text)
                except (ValueError, SyntaxError):
                    return text
            if isinstance(parsed, list):
                return shlex.join(str(part) for part in parsed)
        return text
    if isinstance(value, (list, tuple)):
        return shlex.join(str(part) for part in value)
    return str(value)


def parse_command(text: str) -> list[str]:
    """Inverse of format_command for editable command fields (accepts JSON lists too)."""
    text = (text or "").strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(part) for part in parsed]
        except ValueError:
            pass
    return shlex.split(text)


def mono_font(point_size: int = 10) -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(point_size)
    return font


def enable_on_selection(view: QAbstractItemView, *buttons: QWidget) -> None:
    """Keep item-scoped buttons disabled until the view has a selected row."""

    def sync(*_args) -> None:
        try:
            model = view.selectionModel()
            has = bool(model and model.hasSelection())
            for button in buttons:
                button.setEnabled(has)
        except RuntimeError:  # widget already destroyed during teardown
            pass

    sync()
    if view.selectionModel() is not None:
        view.selectionModel().selectionChanged.connect(sync)
    model = view.model()
    if model is not None:
        model.modelReset.connect(sync)
        model.rowsRemoved.connect(sync)


def stretch_columns(header: QHeaderView, stretch: int, fit: Iterable[int] = ()) -> None:
    """One column takes the free width; the others fit their contents."""
    header.setStretchLastSection(False)
    for column in fit:
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
