"""Original lighthouse scene as a top-anchored panoramic header.

Quadrant cells (four quarters, two colours each) keep the source proportions
at twice the horizontal detail of half blocks. The scene is drawn only
where it stays legible: a wide chat gets the whole panorama, a narrow one
gets the lighthouse and the moon at a readable scale, a shallow one gets a
centred strip, and a chat too small for any of those gets no picture at all.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from rich.cells import cell_len
from rich.text import Text

from isycode.terminal_art import load_raster, quadrant_lines, sample_region


RASTER_PATH = Path(__file__).resolve().parent / "assets" / "isycode_landscape.rgbz"
# Header height ceiling; the chat can request a smaller viewport.
MAX_SCENE_ROWS = 36
# Below this grid the scene is a smear of cells, so it is not drawn.
MIN_SCENE_COLUMNS = 52
MIN_SCENE_ROWS = 8
# Half-cell pixels per source pixel. Shrinking the whole panorama further
# turns it to noise, so narrower chats crop toward the lighthouse instead.
_MIN_SCALE = 0.08
# Source rows that hold the moon, the lantern, its beam and the peaks. A
# shallow header narrows before it shows less than this band.
_SKY_BAND = 180
# Where a horizontal crop sits between the left edge (0) and the right (1):
# far enough right to keep both the lighthouse and the moon.
_CROP_ANCHOR = 0.86


def source_size() -> tuple[int, int]:
    width, height, _ = load_raster(str(RASTER_PATH))
    return width, height


def plan_landscape(width: int, max_rows: int | None = None
                   ) -> tuple[int, int, tuple[int, int, int, int]] | None:
    """Columns, rows and source rectangle for this budget, or None when it cannot be legible."""
    width = int(width)
    limit = MAX_SCENE_ROWS if max_rows is None else min(MAX_SCENE_ROWS, int(max_rows))
    if width < MIN_SCENE_COLUMNS or limit < MIN_SCENE_ROWS:
        return None
    source_width, source_height = source_size()
    scale = max(width / source_width, _MIN_SCALE)
    scale = min(scale, limit * 2 / _SKY_BAND)
    columns = min(width, max(1, round(source_width * scale)))
    rows = min(limit, max(1, int(source_height * scale / 2)))
    crop_width = min(source_width, max(1, round(columns / scale)))
    crop_height = min(source_height, max(1, round(rows * 2 / scale)))
    left = round((source_width - crop_width) * _CROP_ANCHOR)
    return columns, rows, (left, 0, left + crop_width, crop_height)


def landscape_fits(width: int, max_rows: int | None = None) -> bool:
    return plan_landscape(width, max_rows) is not None


@lru_cache(maxsize=8)
def _scene_lines(columns: int, rows: int, box: tuple[int, int, int, int]) -> tuple[Text, ...]:
    return tuple(quadrant_lines(columns, rows,
                                sample_region(RASTER_PATH, box, columns * 2, rows * 2)))


def render_landscape(width: int, max_rows: int | None = None) -> Text:
    """The scene centred in ``width`` cells, or an empty Text when it does not fit."""
    plan = plan_landscape(width, max_rows)
    result = Text()
    if plan is None:
        return result
    columns, rows, box = plan
    lines = _scene_lines(columns, rows, box)
    for index, line in enumerate(lines):
        gap = int(width) - cell_len(line.plain)
        if gap > 0:
            result.append(" " * (gap // 2))
        result.append(line)
        if gap > 0:
            result.append(" " * (gap - gap // 2))
        if index < len(lines) - 1:
            result.append("\n")
    return result


__all__ = ["MAX_SCENE_ROWS", "MIN_SCENE_COLUMNS", "MIN_SCENE_ROWS", "RASTER_PATH",
           "landscape_fits", "plan_landscape", "render_landscape", "source_size"]
