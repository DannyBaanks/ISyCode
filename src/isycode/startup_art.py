"""Startup village drawn at the size the chat shows.

The picture is a night village in the style of the lighthouse scene:
tower, moon, beam, mill wheel, bridge, and warm windows. It is stored
at one pixel per half-cell, so a wide terminal centers it and does not
scale it up. A shorter or narrower chat shrinks it. Width under 42
falls back to the text title. Nothing outside this package is read.
"""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len
from rich.text import Text

from isycode.terminal_art import load_raster, render_half_blocks


RASTER_PATH = Path(__file__).resolve().parent / "assets" / "isycode_landscape.rgbz"
# The drawing is 36 half-block rows. Taller than this, it would be scaled up.
MAX_SCENE_ROWS = 36
_TITLE_STYLE = "bold #e94560"


def source_size() -> tuple[int, int]:
    width, height, _ = load_raster(str(RASTER_PATH))
    return width, height


def render_landscape(width: int, max_rows: int | None = None) -> Text:
    """Center the village. Never grow it, and never wrap a row."""
    width = max(1, int(width))
    if width < 42:
        title = "*  ISYCODE  *"
        horizon = "~" * min(width, len(title) + 8)
        return Text(
            title.center(width)[:width] + "\n" + horizon.center(width)[:width],
            style=_TITLE_STYLE,
        )

    source_w, source_h = source_size()
    native_rows = max(1, source_h // 2)
    limit = native_rows if max_rows is None else max(1, min(native_rows, int(max_rows)))
    columns = min(width, source_w)
    lines = render_half_blocks(RASTER_PATH, columns, limit)
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
