"""ISyCode's ASCIInator city assets for the startup splash.

Source: asciinator_2Oct_001_01.png (2026-10-02)
SHA-256: 24403ebed40e73a4c4a5501cb8e72623d384d928357421df504de7e27f5d5348
The original PNG is bundled for image-capable terminals. A compact raster is
preserved for terminal-cell previews; no Downloads path is read at runtime.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from isycode.terminal_art import load_raster, render_half_blocks

SOURCE_COLUMNS = 220
SOURCE_ROWS = 74
SOURCE_SHA256 = "24403ebed40e73a4c4a5501cb8e72623d384d928357421df504de7e27f5d5348"
ART_PATH = Path(__file__).resolve().parent / "assets" / "asciinator_city.rgbz"
ORIGINAL_PNG = Path(__file__).resolve().parent / "assets" / "asciinator_city.png"


def source_grid() -> bytes:
    """RGB pixels of the bundled source raster."""
    return load_raster(str(ART_PATH))[2]


def render_village(max_width: int, max_height: int) -> list[Text]:
    """Fit the entire city into the terminal with two RGB pixels per cell."""
    return render_half_blocks(ART_PATH, max_width, max_height)


__all__ = ["ART_PATH", "ORIGINAL_PNG", "SOURCE_COLUMNS", "SOURCE_ROWS", "SOURCE_SHA256",
           "render_village", "source_grid"]
