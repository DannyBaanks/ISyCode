"""Fit a small RGB image into a true-color terminal using half-block cells."""

from __future__ import annotations

import struct
import zlib
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


def _box_resize(width: int, height: int, rgb: bytes,
                out_width: int, out_height: int) -> bytes:
    """Average source pixels into each terminal half-cell pixel."""
    result = bytearray(out_width * out_height * 3)
    for out_y in range(out_height):
        y0 = out_y * height // out_height
        y1 = max(y0 + 1, ((out_y + 1) * height + out_height - 1) // out_height)
        for out_x in range(out_width):
            x0 = out_x * width // out_width
            x1 = max(x0 + 1, ((out_x + 1) * width + out_width - 1) // out_width)
            red = green = blue = count = 0
            for source_y in range(y0, min(y1, height)):
                start = (source_y * width + x0) * 3
                for offset in range(0, (min(x1, width) - x0) * 3, 3):
                    red += rgb[start + offset]
                    green += rgb[start + offset + 1]
                    blue += rgb[start + offset + 2]
                    count += 1
            dest = (out_y * out_width + out_x) * 3
            result[dest:dest + 3] = bytes((red // count, green // count, blue // count))
    return bytes(result)


@lru_cache(maxsize=16)
def _scaled(path: str, columns: int, rows: int) -> bytes:
    width, height, rgb = load_raster(path)
    return _box_resize(width, height, rgb, columns, rows * 2)


def sample_half_cells(path: str | Path, max_columns: int, max_rows: int) -> tuple[int, int, bytes]:
    """Return the exact upper/lower RGB pixels used in the terminal preview."""
    path = str(path)
    width, height, _ = load_raster(path)
    columns, rows = fit_cells(width, height, int(max_columns), int(max_rows))
    return columns, rows, _scaled(path, columns, rows) if columns and rows else b""


def render_half_blocks(path: str | Path, max_columns: int, max_rows: int) -> list[Text]:
    """Render the complete raster with independent RGB colors above and below."""
    columns, rows, pixels = sample_half_cells(path, max_columns, max_rows)
    if not columns or not rows:
        return []
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


__all__ = ["decode_raster", "encode_raster", "fit_cells", "load_raster",
           "render_half_blocks", "sample_half_cells"]
