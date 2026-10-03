"""Cell-aligned startup landscape generated from isycode_landscape.gf.

GlyphFuck is an authoring tool only; the installed TUI reads the checked-in
text raster and never needs that sibling repository at runtime.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from rich.text import Text


LANDSCAPE_PATH = Path(__file__).resolve().parent / "assets" / "isycode_landscape.txt"
SCENE_WIDTH = 76


@lru_cache(maxsize=1)
def source_lines() -> tuple[str, ...]:
    lines = LANDSCAPE_PATH.read_text(encoding="utf-8").splitlines()
    if len(lines) != 18 or any(len(line) != SCENE_WIDTH for line in lines):
        raise ValueError("invalid startup landscape raster")
    return tuple(lines)


def _line_style(char: str, x: int, y: int) -> str:
    if char == "#":
        return "bold #e94560"
    if y <= 4 and 34 <= x <= 42 and char != " ":
        return "#f6c77b"
    if char in "*+":
        return "bold #f6c77b"
    if char == "." and y < 7:
        return "#c7d2e4"
    if char in "~_":
        return "#397e90"
    if char in "^|" and y >= 10:
        return "#4aba86"
    return "#567383"


def render_landscape(width: int) -> Text:
    """Center or crop symmetrically; never split the ISYCODE wordmark."""
    width = max(1, int(width))
    if width < 42:
        title = "*  ISYCODE  *"
        horizon = "~" * min(width, len(title) + 8)
        return Text(
            title.center(width)[:width] + "\n" + horizon.center(width)[:width],
            style="bold #e94560",
        )

    start = max(0, (SCENE_WIDTH - width) // 2)
    pad_left = max(0, (width - SCENE_WIDTH) // 2)
    result = Text()
    for y, source in enumerate(source_lines()):
        # An original ASCII cat sits between the trees, inside the existing hero.
        if y in (12, 13):
            cat = r" /\_/\ " if y == 12 else "(=^.^=)"
            left = (SCENE_WIDTH - len(cat)) // 2
            source = source[:left] + cat + source[left + len(cat):]
        row = source[start:start + min(width, SCENE_WIDTH)]
        result.append(" " * pad_left)
        for x, char in enumerate(row, start=start):
            result.append(char, style=_line_style(char, x, y))
        result.append(" " * max(0, width - pad_left - len(row)))
        if y < len(source_lines()) - 1:
            result.append("\n")
    return result


__all__ = ["LANDSCAPE_PATH", "SCENE_WIDTH", "render_landscape", "source_lines"]
