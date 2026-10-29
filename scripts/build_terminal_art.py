#!/usr/bin/env python3
"""Build a compact terminal image and an honest preview from a PNG.

Authoring requires Pillow; the ISyCode runtime only needs the generated .rgbz.
Example:
  PYTHONPATH=src python3 scripts/build_terminal_art.py source.png \
      src/isycode/assets/asciinator_city.rgbz --preview /tmp/city-preview.png
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image

from isycode.terminal_art import encode_raster, sample_half_cells


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="source PNG exported by ASCIInator")
    parser.add_argument("output", type=Path, help="package .rgbz path")
    parser.add_argument("--width", type=int, default=240, help="embedded raster width")
    parser.add_argument("--height", type=int, default=160, help="embedded raster height")
    parser.add_argument("--columns", type=int, default=90, help="preview terminal columns")
    parser.add_argument("--rows", type=int, default=30, help="preview terminal rows")
    parser.add_argument("--preview", type=Path, help="write the exact terminal pixel preview")
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0:
        parser.error("raster dimensions must be positive")
    source = args.source.read_bytes()
    # Preserve the source glyph color while shrinking. Compositing alpha
    # before resampling makes the tiny colored characters nearly disappear.
    image = Image.open(args.source).convert("RGBA")
    raster = image.resize((args.width, args.height), Image.Resampling.LANCZOS).convert("RGB")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encode_raster(args.width, args.height, raster.tobytes()))
    print(f"source SHA-256: {hashlib.sha256(source).hexdigest()}")
    print(f"raster: {args.width}x{args.height} -> {args.output}")
    if args.preview:
        columns, rows, pixels = sample_half_cells(args.output, args.columns, args.rows)
        preview = Image.frombytes("RGB", (columns, rows * 2), pixels)
        preview.resize((columns * 10, rows * 20), Image.Resampling.NEAREST).save(args.preview)
        print(f"terminal preview: {columns}x{rows} cells -> {args.preview}")


if __name__ == "__main__":
    main()
