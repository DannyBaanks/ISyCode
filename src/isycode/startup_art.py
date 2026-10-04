"""Original lighthouse scene as a full-width, top-anchored panoramic header.

Half-block cells preserve the source proportions. Wide or short terminals
crop the bottom of the scene instead of enlarging it beyond the row budget.
"""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len
from rich.text import Text

from isycode.terminal_art import load_raster, render_half_blocks


RASTER_PATH = Path(__file__).resolve().parent / "assets" / "isycode_landscape.rgbz"
# Header height ceiling; the chat can request a smaller viewport.
MAX_SCENE_ROWS = 36
_TITLE_STYLE = "bold #e94560"


def source_size() -> tuple[int, int]:
    width, height, _ = load_raster(str(RASTER_PATH))
    return width, height


def render_landscape(width: int, max_rows: int | None = None) -> Text:
    """Fill the chat width within its row budget, without wrapping."""
    width = max(1, int(width))
    if width < 42:
        title = "*  ISYCODE  *"
        horizon = "~" * min(width, len(title) + 8)
        return Text(
            title.center(width)[:width] + "\n" + horizon.center(width)[:width],
            style=_TITLE_STYLE,
        )

    limit = MAX_SCENE_ROWS if max_rows is None else max(1, min(MAX_SCENE_ROWS, int(max_rows)))
    lines = render_half_blocks(RASTER_PATH, width, limit, cover_top=True)
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
