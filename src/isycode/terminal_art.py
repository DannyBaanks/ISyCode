"""Fit a small RGB image into a true-color terminal using half-block cells."""

from __future__ import annotations

import struct
import sys
import zlib
from array import array
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

from rich.text import Text


_MAGIC = b"ISYART01"


def encode_raster(width: int, height: int, rgb: bytes) -> bytes:
    """Serialize a raster without requiring an image library at runtime."""
    if width <= 0 or height <= 0 or len(rgb) != width * height * 3:
        raise ValueError("invalid RGB raster")
    return _MAGIC + struct.pack(">II", width, height) + zlib.compress(rgb, 9)


def decode_raster(data: bytes) -> tuple[int, int, bytes]:
    if len(data) < 16 or not data.startswith(_MAGIC):
        raise ValueError("invalid terminal art header")
    width, height = struct.unpack(">II", data[8:16])
    if width <= 0 or height <= 0 or width * height > 1_000_000:
        raise ValueError("invalid terminal art dimensions")
    try:
        rgb = zlib.decompress(data[16:])
    except zlib.error as exc:
        raise ValueError("invalid terminal art pixels") from exc
    if len(rgb) != width * height * 3:
        raise ValueError("invalid terminal art pixels")
    return width, height, rgb


@lru_cache(maxsize=8)
def load_raster(path: str) -> tuple[int, int, bytes]:
    return decode_raster(Path(path).read_bytes())


def fit_cells(width: int, height: int, max_columns: int, max_rows: int) -> tuple[int, int]:
    """Keep square half-cell pixels and the source image's proportions."""
    if max_columns < 1 or max_rows < 1:
        return 0, 0
    columns = min(max_columns, max(1, round(max_rows * 2 * width / height)))
    rows = min(max_rows, max(1, round(columns * height / (2 * width))))
    return columns, rows


def _linear(value: int) -> int:
    channel = value / 255
    light = channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
    return round(light * 65535)


# sRGB bytes are not amounts of light: averaging them directly dims every
# lantern, window and star that shares a cell with the night around it.
_LINEAR = tuple(_linear(value) for value in range(256))
_LINEAR_LOW = bytes(value & 255 for value in _LINEAR)
_LINEAR_HIGH = bytes(value >> 8 for value in _LINEAR)
_SRGB_EDGES = tuple((_LINEAR[value] + _LINEAR[value + 1]) / 2 for value in range(255))
_LITTLE = sys.byteorder == "little"
# One 32-bit lane per channel; a column of 16-bit light values this tall cannot overflow it.
_LANE_ROWS = 65536


def _box_resize(width: int, height: int, rgb: bytes,
                out_width: int, out_height: int) -> bytes:
    """Average the light of the source block behind each terminal half-cell pixel.

    This is the only resampler the module keeps: the header grid is always much
    smaller than its source, so point sampling would throw away most of the
    image instead of shrinking it. Rows are added as whole integers and columns
    as array slices, so a resize costs milliseconds while a window is dragged.
    """
    lanes = bytearray(len(rgb) * 4)
    lanes[0 if _LITTLE else 3::4] = rgb.translate(_LINEAR_LOW)
    lanes[1 if _LITTLE else 2::4] = rgb.translate(_LINEAR_HIGH)
    stride = width * 12
    view = memoryview(lanes)
    source_rows = [int.from_bytes(view[start:start + stride], sys.byteorder)
                   for start in range(0, height * stride, stride)]
    spans = []
    for out_x in range(out_width):
        x0 = out_x * width // out_width
        x1 = min(width, max(x0 + 1, ((out_x + 1) * width + out_width - 1) // out_width))
        spans.append((x0 * 3, x1 * 3, x1 - x0))
    result = bytearray(out_width * out_height * 3)
    dest = 0
    for out_y in range(out_height):
        y0 = out_y * height // out_height
        y1 = min(height, y0 + _LANE_ROWS,
                 max(y0 + 1, ((out_y + 1) * height + out_height - 1) // out_height))
        light = array("I")
        light.frombytes(sum(source_rows[y0:y1]).to_bytes(stride, sys.byteorder))
        for start, stop, columns in spans:
            count = columns * (y1 - y0)
            result[dest] = bisect_right(_SRGB_EDGES, sum(light[start:stop:3]) / count)
            result[dest + 1] = bisect_right(_SRGB_EDGES, sum(light[start + 1:stop:3]) / count)
            result[dest + 2] = bisect_right(_SRGB_EDGES, sum(light[start + 2:stop:3]) / count)
            dest += 3
    return bytes(result)


@lru_cache(maxsize=16)
def _scaled(path: str, columns: int, rows: int, cover_top: bool = False) -> bytes:
    """Area-average the source into the half-cell grid.

    The target grid is small (a 247-column terminal paints 247x72 pixels, one
    per half cell), so every output pixel stands for a whole block of source
    pixels. Point sampling keeps one of them and discards the rest, which ate
    the moon, the mountains and the clouds into hard aliased edges. Averaging
    the block uses all of them and is what makes the scene legible once it is
    that small. ``cover_top`` only trims the bottom; it no longer changes the
    filter.
    """
    width, height, rgb = load_raster(path)
    if cover_top:
        # Keep the lighthouse and moon: crop the bottom, then resample.
        height = min(height, max(1, round(width * rows * 2 / columns)))
        rgb = rgb[:width * height * 3]
    return _box_resize(width, height, rgb, columns, rows * 2)


@lru_cache(maxsize=16)
def _scaled_region(path: str, box: tuple[int, int, int, int],
                   out_width: int, out_height: int) -> bytes:
    width, height, rgb = load_raster(path)
    left, top, right, bottom = box
    left, right = max(0, left), min(width, right)
    top, bottom = max(0, top), min(height, bottom)
    if (left, right) != (0, width):
        rgb = b"".join(rgb[(y * width + left) * 3:(y * width + right) * 3]
                       for y in range(top, bottom))
    else:
        rgb = rgb[top * width * 3:bottom * width * 3]
    return _box_resize(right - left, bottom - top, rgb, out_width, out_height)


def sample_half_cells(path: str | Path, max_columns: int, max_rows: int, *,
                      cover_top: bool = False) -> tuple[int, int, bytes]:
    """Return the exact upper/lower RGB pixels used in the terminal preview."""
    path = str(path)
    width, height, _ = load_raster(path)
    columns, rows = fit_cells(width, height, int(max_columns), int(max_rows))
    if cover_top and columns and rows:
        columns = int(max_columns)
    return columns, rows, _scaled(path, columns, rows, cover_top) if columns and rows else b""


def sample_region(path: str | Path, box: tuple[int, int, int, int],
                  out_width: int, out_height: int) -> bytes:
    """RGB pixels of one source rectangle averaged into an ``out_width`` x ``out_height`` grid."""
    return _scaled_region(str(path), tuple(int(edge) for edge in box),
                          int(out_width), int(out_height))


# Quadrant glyph for each set of lit quarters (top-left 1, top-right 2,
# bottom-left 4, bottom-right 8). The top-left quarter is always foreground,
# so only the odd masks are needed.
_QUADRANTS = {1: "▘", 3: "▀", 5: "▌", 7: "▛", 9: "▚", 11: "▜", 13: "▙"}
QUADRANT_GLYPHS = frozenset(_QUADRANTS.values())
# Squared RGB distance under which a cell is treated as a smooth gradient.
_FLAT_CELL = 3 * 14 * 14


def _mean(colors: list[tuple[int, int, int]]) -> str:
    count = len(colors)
    return "#{:02x}{:02x}{:02x}".format(sum(c[0] for c in colors) // count,
                                        sum(c[1] for c in colors) // count,
                                        sum(c[2] for c in colors) // count)


def quadrant_lines(columns: int, rows: int, pixels: bytes) -> list[Text]:
    """Draw a ``2*columns`` x ``2*rows`` pixel grid with four quarters per cell.

    A cell holds two colours, so each one is split into the two groups of
    quarters that differ most. That resolves vertical edges as well as
    horizontal ones: twice the horizontal detail of half blocks. A cell with
    no real edge keeps the upper/lower half block, which carries gradients.
    """
    grid_width = columns * 2
    lines: list[Text] = []
    for row in range(rows):
        upper = row * 2 * grid_width * 3
        lower = upper + grid_width * 3
        line = Text()
        for col in range(columns):
            a, b = upper + col * 6, lower + col * 6
            quarters = (tuple(pixels[a:a + 3]), tuple(pixels[a + 3:a + 6]),
                        tuple(pixels[b:b + 3]), tuple(pixels[b + 3:b + 6]))
            far, first, second = -1, 0, 1
            for i in range(3):
                p = quarters[i]
                for j in range(i + 1, 4):
                    q = quarters[j]
                    distance = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2
                    if distance > far:
                        far, first, second = distance, i, j
            if far < _FLAT_CELL:
                mask = 3
            else:
                p, q = quarters[first], quarters[second]
                mask = 0
                for index, c in enumerate(quarters):
                    near = (c[0] - p[0]) ** 2 + (c[1] - p[1]) ** 2 + (c[2] - p[2]) ** 2
                    away = (c[0] - q[0]) ** 2 + (c[1] - q[1]) ** 2 + (c[2] - q[2]) ** 2
                    if near <= away:
                        mask |= 1 << index
                if not mask & 1:
                    mask ^= 15
            fg = _mean([c for index, c in enumerate(quarters) if mask >> index & 1])
            bg = _mean([c for index, c in enumerate(quarters) if not mask >> index & 1])
            line.append(_QUADRANTS[mask], style=f"{fg} on {bg}")
        lines.append(line)
    return lines


def half_block_lines(columns: int, rows: int, pixels: bytes) -> list[Text]:
    """One Text per terminal row, with independent RGB colors above and below."""
    lines: list[Text] = []
    for row in range(rows):
        line = Text()
        for col in range(columns):
            top = (row * 2 * columns + col) * 3
            bottom = top + columns * 3
            upper = pixels[top:top + 3]
            lower = pixels[bottom:bottom + 3]
            fg = "#{:02x}{:02x}{:02x}".format(*upper)
            bg = "#{:02x}{:02x}{:02x}".format(*lower)
            line.append("▀", style=f"{fg} on {bg}")
        lines.append(line)
    return lines


def render_half_blocks(path: str | Path, max_columns: int, max_rows: int, *,
                       cover_top: bool = False) -> list[Text]:
    """Render the complete raster with independent RGB colors above and below."""
    columns, rows, pixels = sample_half_cells(path, max_columns, max_rows, cover_top=cover_top)
    if not columns or not rows:
        return []
    return half_block_lines(columns, rows, pixels)


__all__ = ["QUADRANT_GLYPHS", "decode_raster", "encode_raster", "fit_cells", "half_block_lines",
           "load_raster", "quadrant_lines", "render_half_blocks", "sample_half_cells", "sample_region"]
