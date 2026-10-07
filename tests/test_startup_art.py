"""The original lighthouse fills a bounded, responsive terminal header."""
from rich.cells import cell_len
from isycode.startup_art import MAX_SCENE_ROWS, RASTER_PATH, render_landscape
from isycode.terminal_art import decode_raster, sample_half_cells


def test_header_uses_original_picture_resolution():
    width, height, rgb = decode_raster(RASTER_PATH.read_bytes())
    assert width >= 768 and height >= 512
    assert len(rgb) == width * height * 3


def test_header_fills_width_without_growing_past_height_budget():
    for width, budget in [(90, 40), (180, 40), (240, 36), (160, 12)]:
        lines = render_landscape(width, budget).plain.splitlines()
        assert 1 <= len(lines) <= min(budget, MAX_SCENE_ROWS)
        assert all(cell_len(line) == width and line.count('▀') == width for line in lines)
    assert len(render_landscape(180, 40).plain.splitlines()) == 36


def test_wide_header_keeps_a_bright_moon_against_a_dark_sky():
    columns, rows, pixels = sample_half_cells(RASTER_PATH, 180, 36, cover_top=True)
    assert (columns, rows) == (180, 36)

    def luminance(x, y):
        start = (y * columns + x) * 3
        red, green, blue = pixels[start:start + 3]
        return red + green + blue

    sky = min(luminance(x, y) for y in range(6) for x in range(12))
    moon = max(luminance(x, y) for y in range(rows // 3) for x in range(int(columns * 0.8), columns))
    assert sky < 80
    assert moon > 600


def test_small_terminal_keeps_text_fallback():
    lines = render_landscape(24).plain.splitlines()
    assert all(cell_len(line) == 24 for line in lines)
    assert any('ISYCODE' in line for line in lines)
