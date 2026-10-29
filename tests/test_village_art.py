"""The idle city is fitted from the actual ASCIInator PNG export."""

from isycode.terminal_art import decode_raster, encode_raster, sample_half_cells
from isycode.village_art import ART_PATH, ORIGINAL_PNG, SOURCE_COLUMNS, SOURCE_ROWS, SOURCE_SHA256, render_village, source_grid
import hashlib
import struct


def test_original_png_is_bundled_without_downsampling():
    assert hashlib.sha256(ORIGINAL_PNG.read_bytes()).hexdigest() == SOURCE_SHA256
    data = ORIGINAL_PNG.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (6456, 4338)


def test_bundled_city_raster_is_complete_and_independent_of_downloads():
    assert (SOURCE_COLUMNS, SOURCE_ROWS) == (220, 74)
    width, height, rgb = decode_raster(ART_PATH.read_bytes())
    assert (width, height) == (240, 160)
    assert rgb == source_grid()
    assert len(rgb) == width * height * 3
    assert max(rgb) > 200


def test_terminal_city_keeps_roofs_lights_and_black_sky():
    columns, rows, pixels = sample_half_cells(ART_PATH, 78, 26)
    assert (columns, rows) == (78, 26)
    assert len(pixels) == columns * rows * 2 * 3

    def pixel(x, y):
        start = (y * columns + x) * 3
        return tuple(pixels[start:start + 3])

    roof = pixel(36, 6)
    house = pixel(14, 28)
    moon = pixel(66, 5)
    sky = pixel(2, 50)
    assert roof[0] > roof[2] * 3
    assert house[0] > house[2] * 3
    assert min(moon) > 180
    assert sky == (0, 0, 0)

    art = render_village(78, 26)
    assert len(art) == 26
    assert all(line.plain == "▀" * 78 for line in art)
    assert any(" on #" in str(span.style) for line in art for span in line.spans)


def test_narrow_city_preserves_proportions_and_invalid_raster_is_rejected():
    art = render_village(40, 8)
    assert len(art) == 8
    assert all(len(line.plain) == 24 for line in art)
    assert decode_raster(encode_raster(1, 1, b"\x01\x02\x03")) == (1, 1, b"\x01\x02\x03")
