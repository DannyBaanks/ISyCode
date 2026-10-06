"""Side-by-side diff rendering in the ISyCode theme.

Parses unified diffs into aligned old/new columns with real line numbers
and tinted rows (removed: red tint left, added: green tint right) — the
structure of the OpenCode diff view with our palette. Presentation only.
"""
from __future__ import annotations

from dataclasses import dataclass

from rich.table import Table
from rich.text import Text

REMOVED_BG = "#3a1d24"
ADDED_BG = "#1d3324"
NUMBER_STYLE = "#6c757d"
CONTEXT_STYLE = "#e0e0e0"
PATH_STYLE = "bold #bb8cff"
HUNK_STYLE = "#9aa3ad"


@dataclass
class DiffRow:
    kind: str
    old_no: int | None
    new_no: int | None
    text: str


@dataclass
class Hunk:
    old_start: int
    new_start: int
    rows: list[DiffRow]


def parse_unified_diff(diff: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    current: Hunk | None = None
    old_no = new_no = 0
    for raw in diff.splitlines():
        if raw.startswith("@@"):
            header = raw.split("@@")[1].strip()
            old_part, new_part = header.split(" ")
            old_no = int(old_part.removeprefix("-").split(",")[0])
            new_no = int(new_part.removeprefix("+").split(",")[0])
            current = Hunk(old_no, new_no, [])
            hunks.append(current)
            continue
        if current is None or raw.startswith(("---", "+++", "\\")):
            continue
        if raw.startswith("-"):
            current.rows.append(DiffRow("del", old_no, None, raw[1:]))
            old_no += 1
        elif raw.startswith("+"):
            current.rows.append(DiffRow("add", None, new_no, raw[1:]))
            new_no += 1
        else:
            text = raw[1:] if raw.startswith(" ") else raw
            current.rows.append(DiffRow("context", old_no, new_no, text))
            old_no += 1
            new_no += 1
    return [hunk for hunk in hunks if hunk.rows]


def _number_cell(number: int | None) -> Text:
    return Text(f"{number:>4} " if number is not None else " " * 5, style=NUMBER_STYLE)


def _line_cell(number: int | None, text: str, background: str | None) -> Text:
    cell = _number_cell(number)
    style = f"{CONTEXT_STYLE} on {background}" if background else CONTEXT_STYLE
    cell.append(text or " ", style=style)
    return cell


def hunk_rows(hunk: Hunk) -> list[tuple[Text, Text]]:
    """Aligned (old, new) cell pairs; change rows padded on the other side."""
    pairs: list[tuple[Text, Text]] = []
    for row in hunk.rows:
        if row.kind == "del":
            pairs.append((_line_cell(row.old_no, row.text, REMOVED_BG),
                          _line_cell(None, "", None)))
        elif row.kind == "add":
            pairs.append((_line_cell(None, "", None),
                          _line_cell(row.new_no, row.text, ADDED_BG)))
        else:
            pairs.append((_line_cell(row.old_no, row.text, None),
                          _line_cell(row.new_no, row.text, None)))
    return pairs


def side_by_side_table(diff: str, path: str, *, width: int = 100) -> Table:
    """One table per diff: header row with the path, then aligned hunks."""
    table = Table.grid(expand=True)
    table.add_column(ratio=1, no_wrap=True, overflow="fold")
    table.add_column(ratio=1, no_wrap=True, overflow="fold")
    half = max(20, (width - 4) // 2)
    table.add_row(Text(f"← {path}", style=PATH_STYLE), Text(""))
    for hunk in parse_unified_diff(diff):
        table.add_row(
            Text(f"@@ -{hunk.old_start} +{hunk.new_start} @@", style=HUNK_STYLE),
            Text("", style=HUNK_STYLE))
        for old_cell, new_cell in hunk_rows(hunk):
            old_cell.truncate(half, overflow="ellipsis")
            new_cell.truncate(half, overflow="ellipsis")
            table.add_row(old_cell, new_cell)
    return table


__all__ = ["parse_unified_diff", "hunk_rows", "side_by_side_table",
           "REMOVED_BG", "ADDED_BG"]
