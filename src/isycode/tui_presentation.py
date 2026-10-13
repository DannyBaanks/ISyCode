"""Responsive menu geometry; display values never carry action authority."""
from dataclasses import dataclass

from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.text import Text

from isycode.tui_theme import MUTED, TEXT


@dataclass(frozen=True)
class SettingRow:
    label: str
    value: str
    help: str = ""
    value_style: str = TEXT

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = options.max_width
        # Local help moves to the persistent preview at smaller widths.
        help_width = max(0, width - 52) if width >= 78 else 0
        name_width = min(26, max(12, (width - help_width - 2) // 2))
        value_width = max(1, width - name_width - help_width - (4 if help_width else 2))
        row = Table.grid(padding=(0, 1), expand=True)
        row.add_column(width=name_width, no_wrap=True, overflow="ellipsis")
        row.add_column(width=value_width, no_wrap=True, overflow="ellipsis")
        cells = [Text(self.label, style=TEXT), Text(self.value, style=self.value_style)]
        if help_width:
            row.add_column(width=help_width, no_wrap=True, overflow="ellipsis")
            cells.append(Text(self.help, style=MUTED))
        row.add_row(*cells)
        yield row


@dataclass(frozen=True)
class MenuHeading:
    title: str
    scope: str = ""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        row = Table.grid(expand=True)
        row.add_column(ratio=2, no_wrap=True, overflow="ellipsis")
        row.add_column(ratio=1, justify="right", no_wrap=True, overflow="ellipsis")
        row.add_row(Text(self.title, style=f"bold {TEXT}"), Text(self.scope, style=MUTED))
        yield row
