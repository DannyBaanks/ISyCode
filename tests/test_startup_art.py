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


def _point_sample_frame(columns, rows, cover_top=True):
    """Rebuild what point sampling used to produce, for the regression below.

    Kept as a local helper so the test states the old behaviour explicitly
    instead of depending on a deleted private function.
    """
    from isycode.terminal_art import load_raster
    width, height, rgb = load_raster(str(RASTER_PATH))
    if cover_top:
        height = min(height, max(1, round(width * rows * 2 / columns)))
        rgb = rgb[:width * height * 3]
    out_height, out_width = rows * 2, columns
    result = bytearray(out_width * out_height * 3)
    for out_y in range(out_height):
        source_y = min(height - 1, out_y * height // out_height)
        row = source_y * width
        for out_x in range(out_width):
            source_x = min(width - 1, out_x * width // out_width)
            start = (row + source_x) * 3
            dest = (out_y * out_width + out_x) * 3
            result[dest:dest + 3] = rgb[start:start + 3]
    return bytes(result)


def test_header_averages_its_source_instead_of_point_sampling():
    """Audit 2026-10-09: point sampling destroyed the scene at header size.

    The header grid is far smaller than the source raster, so keeping one
    pixel per cell threw the rest away and left the mountains, the clouds and
    the moon as hard, aliased blocks. Averaging the block behind each cell is
    what makes the reduced image legible.
    """
    columns, rows, pixels = sample_half_cells(RASTER_PATH, 247, 36, cover_top=True)
    old = _point_sample_frame(columns, rows)

    def difference(candidate):
        return sum(abs(a - b) for a, b in zip(candidate, old)) / len(old)

    # The pipeline must no longer agree with point sampling.
    assert difference(pixels) > 5.0

    # And it must sit much closer to the true local average of the source.
    from isycode.terminal_art import _box_resize, load_raster
    width, height, rgb = load_raster(str(RASTER_PATH))
    crop_h = min(height, max(1, round(width * rows * 2 / columns)))
    exact = _box_resize(width, crop_h, rgb[:width * crop_h * 3], columns, rows * 2)
    assert pixels == exact
    assert difference(exact) > 5.0


def test_reduced_header_keeps_smooth_gradients_in_the_sky():
    """Averaging must not collapse the dark sky into one flat value band."""
    columns, rows, pixels = sample_half_cells(RASTER_PATH, 247, 36, cover_top=True)

    def values(y):
        start = (y * columns) * 3
        return [pixels[start + x * 3] for x in range(columns)]

    # The top rows are night sky: averaging must preserve many distinct levels
    # instead of snapping them to a handful of point-sampled values.
    for y in (0, 1, 2):
        levels = len(set(values(y)))
        assert levels > 12, f"sky row {y} lost its gradient ({levels} levels)"
