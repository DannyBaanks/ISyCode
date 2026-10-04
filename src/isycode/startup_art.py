"""Night landscape for the startup splash.

The checked-in raster is the artwork. Black pixels are unlit dots, so the
terminal background shows through. Each cell packs a 2×4 neighborhood into
Unicode Braille and takes the average color of its lit dots. Nothing outside
this package is read at runtime.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from rich.text import Text

from isycode.terminal_art import load_raster


LANDSCAPE_PATH = Path(__file__).resolve().parent / "assets" / "isycode_landscape.txt"
RASTER_PATH = Path(__file__).resolve().parent / "assets" / "isycode_landscape.rgbz"
SCENE_WIDTH = 76
SCENE_HEIGHT = 18
DOT_WIDTH = 152
DOT_HEIGHT = 72
_WORD = "ISYCODE"
_WORD_ROW = 1
_WORD_STYLE = "bold #e94560"
# Braille dots, left then right, top to bottom. Dot 4 and dot 8 are the bottom pair.
_BITS = ((1, 8), (2, 16), (4, 32), (64, 128))


@lru_cache(maxsize=1)
def _scene() -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    width, height, rgb = load_raster(str(RASTER_PATH))
    if (width, height) != (DOT_WIDTH, DOT_HEIGHT):
        raise ValueError("invalid startup landscape raster")
    lines: list[list[str]] = []
    styles: list[list[str]] = []
    for cell_y in range(SCENE_HEIGHT):
        row: list[str] = []
        row_styles: list[str] = []
        for cell_x in range(SCENE_WIDTH):
            mask = 0
            red = green = blue = count = 0
            for dot_y in range(4):
                for dot_x in range(2):
                    offset = ((cell_y * 4 + dot_y) * width + (cell_x * 2 + dot_x)) * 3
                    sample = rgb[offset:offset + 3]
                    if sample[0] or sample[1] or sample[2]:
                        mask |= _BITS[dot_y][dot_x]
                        red += sample[0]
                        green += sample[1]
                        blue += sample[2]
                        count += 1
            if mask and count:
                row.append(chr(0x2800 + mask))
                row_styles.append(f"#{red // count:02x}{green // count:02x}{blue // count:02x}")
            else:
                row.append(" ")
                row_styles.append("")
        lines.append(row)
        styles.append(row_styles)
    word_at = (SCENE_WIDTH - len(_WORD)) // 2
    for index in (word_at - 1, word_at + len(_WORD)):
        lines[_WORD_ROW][index] = " "
        styles[_WORD_ROW][index] = ""
    for offset, char in enumerate(_WORD):
        lines[_WORD_ROW][word_at + offset] = char
        styles[_WORD_ROW][word_at + offset] = _WORD_STYLE
    packed = tuple("".join(row) for row in lines)
    if len(packed) != SCENE_HEIGHT or any(len(line) != SCENE_WIDTH for line in packed):
        raise ValueError("invalid startup landscape raster")
    return packed, tuple(tuple(row) for row in styles)


def source_lines() -> tuple[str, ...]:
    return _scene()[0]


def render_landscape(width: int) -> Text:
    """Center or crop symmetrically. The name stays whole at every width."""
    width = max(1, int(width))
    if width < 42:
        title = "*  ISYCODE  *"
        horizon = "~" * min(width, len(title) + 8)
        return Text(
            title.center(width)[:width] + "\n" + horizon.center(width)[:width],
            style=_WORD_STYLE,
        )

    lines, styles = _scene()
    start = max(0, (SCENE_WIDTH - width) // 2)
    pad_left = max(0, (width - SCENE_WIDTH) // 2)
    result = Text()
    for y, source in enumerate(lines):
        row = source[start:start + min(width, SCENE_WIDTH)]
        result.append(" " * pad_left)
        for x, char in enumerate(row):
            style = styles[y][start + x]
            if style:
                result.append(char, style=style)
            else:
                result.append(char)
        result.append(" " * max(0, width - pad_left - len(row)))
        if y < len(lines) - 1:
            result.append("\n")
    return result


__all__ = ["LANDSCAPE_PATH", "RASTER_PATH", "SCENE_WIDTH", "render_landscape", "source_lines"]
