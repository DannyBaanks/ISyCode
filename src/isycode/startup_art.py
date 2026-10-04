"""Startup landscape from the bundled night-village raster.

The picture is the original village: lighthouse, moon, bridge, and mill.
Each cell is a half-block with its own upper and lower color. The renderer
keeps the picture's proportions and stops at MAX_SCENE_ROWS so the village
stays on screen. A very narrow terminal falls back to the text title.
Nothing outside this package is read.
"""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len
from rich.text import Text

from isycode.terminal_art import load_raster, render_half_blocks


RASTER_PATH = Path(__file__).resolve().parent / "assets" / "isycode_landscape.rgbz"
# Taller than this, the village covers the model line and the chat stops scrolling.
MAX_SCENE_ROWS = 30
_TITLE_STYLE = "bold #e94560"


def source_size() -> tuple[int, int]:
    width, height, _ = load_raster(str(RASTER_PATH))
    return width, height


def render_landscape(width: int, max_rows: int | None = None) -> Text:
    """Fit the whole village inside the chat. Never wrap a row."""
    width = max(1, int(width))
    if width < 42:
        title = "*  ISYCODE  *"
        horizon = "~" * min(width, len(title) + 8)
        return Text(
            title.center(width)[:width] + "\n" + horizon.center(width)[:width],
            style=_TITLE_STYLE,
        )

    source_w, source_h = source_size()
    natural = max(1, round(width * source_h / (2 * source_w)))
    limit = MAX_SCENE_ROWS if max_rows is None else max(1, int(max_rows))
    rows = min(natural, limit)
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


__all__ = ["MAX_SCENE_ROWS", "RASTER_PATH", "render_landscape", "source_size"]
