"""Startup landscape from the bundled night-village raster.

The picture is the original village: lighthouse, moon, bridge, and mill.
Each cell is a half-block with its own upper and lower color. The renderer
uses the full chat width and keeps the picture's proportions. A very narrow
terminal falls back to the text title. Nothing outside this package is read.
"""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len
from rich.text import Text

from isycode.terminal_art import load_raster, render_half_blocks


RASTER_PATH = Path(__file__).resolve().parent / "assets" / "isycode_landscape.rgbz"
_TITLE_STYLE = "bold #e94560"


def source_size() -> tuple[int, int]:
    width, height, _ = load_raster(str(RASTER_PATH))
    return width, height


def render_landscape(width: int) -> Text:
    """Fit the village to the chat width. Never wrap a row."""
    width = max(1, int(width))
    if width < 42:
        title = "*  ISYCODE  *"
        horizon = "~" * min(width, len(title) + 8)
        return Text(
            title.center(width)[:width] + "\n" + horizon.center(width)[:width],
            style=_TITLE_STYLE,
        )

    source_w, source_h = source_size()
    rows = max(1, round(width * source_h / (2 * source_w)))
    lines = render_half_blocks(RASTER_PATH, width, rows)
    result = Text()
    for index, line in enumerate(lines):
        gap = width - cell_len(line.plain)
        if gap > 0:
            result.append(" " * (gap // 2))
        result.append(line)
        if gap > 0:
            result.append(" " * (gap - gap // 2))
        if index < len(lines) - 1:
            result.append("\n")
    return result


__all__ = ["RASTER_PATH", "render_landscape", "source_size"]
