"""The original lighthouse fills a bounded, responsive terminal header."""
from rich.cells import cell_len
from isycode.startup_art import (MAX_SCENE_ROWS, MIN_SCENE_COLUMNS, MIN_SCENE_ROWS, RASTER_PATH,
                                 landscape_fits, plan_landscape, render_landscape, source_size)
from isycode.terminal_art import QUADRANT_GLYPHS, decode_raster, sample_half_cells


def _art_cells(line):
    return sum(char in QUADRANT_GLYPHS for char in line)


def test_header_uses_original_picture_resolution():
    width, height, rgb = decode_raster(RASTER_PATH.read_bytes())
    assert width >= 768 and height >= 512
    assert len(rgb) == width * height * 3


def test_header_fills_width_without_growing_past_height_budget():
    for width, budget in [(90, 40), (180, 40), (240, 36), (160, 12)]:
        lines = render_landscape(width, budget).plain.splitlines()
        assert 1 <= len(lines) <= min(budget, MAX_SCENE_ROWS)
        assert all(cell_len(line) == width and _art_cells(line) == width for line in lines)
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


def test_a_grid_too_small_to_read_gets_no_picture_at_all():
    """A cramped window drops the scene instead of smearing it or printing a stand-in."""
    for width, budget in [(24, 30), (MIN_SCENE_COLUMNS - 1, 36), (120, MIN_SCENE_ROWS - 1), (200, 0), (0, 0)]:
        assert not landscape_fits(width, budget)
        assert render_landscape(width, budget).plain == ""
    assert landscape_fits(MIN_SCENE_COLUMNS, MIN_SCENE_ROWS)


def test_every_size_that_fits_stays_inside_its_budget_and_its_source():
    source_width, source_height = source_size()
    for width in range(MIN_SCENE_COLUMNS, 320, 7):
        for budget in (MIN_SCENE_ROWS, 11, 20, 36, 60):
            columns, rows, (left, top, right, bottom) = plan_landscape(width, budget)
            assert MIN_SCENE_COLUMNS <= columns <= width
            assert MIN_SCENE_ROWS <= rows <= min(budget, MAX_SCENE_ROWS)
            assert 0 <= left < right <= source_width and 0 == top < bottom <= source_height
            # Square half-cell pixels: the crop and the grid share one aspect ratio.
            assert abs((right - left) / (bottom - top) - columns / (rows * 2)) < 0.12 * columns / (rows * 2)
    lines = render_landscape(61, 9).plain.splitlines()
    assert len(lines) == 9 and all(cell_len(line) == 61 for line in lines)


def test_narrow_chat_crops_to_the_lighthouse_and_moon_instead_of_shrinking():
    source_width, _ = source_size()
    columns, rows, (left, _top, right, _bottom) = plan_landscape(60, 30)
    assert columns == 60
    assert right - left < source_width
    # Lantern (x≈540–650) and moon (x≈1025–1100) of the 1224-wide source both survive.
    assert left <= 0.44 * source_width and right >= 0.90 * source_width
    wide = plan_landscape(140, 30)
    assert (wide[2][0], wide[2][2]) == (0, source_width)


def test_shallow_wide_chat_centres_a_strip_that_still_shows_the_moon_and_lantern():
    columns, rows, (_left, _top, _right, bottom) = plan_landscape(200, 8)
    assert rows == 8 and columns < 200
    assert bottom >= 170
    lines = render_landscape(200, 8).plain.splitlines()
    assert all(cell_len(line) == 200 and _art_cells(line) == columns for line in lines)
    margin = len(lines[0]) - len(lines[0].lstrip(' '))
    assert abs(margin - (200 - columns) / 2) <= 1


def test_lights_are_averaged_as_light_so_they_survive_reduction():
    """A lit window sharing a cell with the night must not be dimmed toward it."""
    from isycode.terminal_art import _box_resize
    block = bytes([255, 255, 255]) + bytes(9)          # one white pixel, three black
    plain_mean = 255 // 4
    assert _box_resize(2, 2, block, 1, 1)[0] > plain_mean * 2
    flat = bytes([37, 120, 201]) * 12
    assert _box_resize(4, 3, flat, 2, 1) == bytes([37, 120, 201]) * 2


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


def test_cells_split_into_quarters_resolve_vertical_edges():
    """Half blocks cannot show a left/right edge inside a cell; quadrant cells can."""
    from isycode.terminal_art import quadrant_lines
    white, black = bytes([255, 255, 255]), bytes(3)
    left_right = (white + black) * 2                      # one cell: left column lit
    (line,) = quadrant_lines(1, 1, left_right)
    assert line.plain == "▌"
    style = line.spans[0].style
    assert "#ffffff on #000000" == str(style)
    diagonal = white + black + black + white
    assert quadrant_lines(1, 1, diagonal)[0].plain == "▚"
    # No edge in the cell: keep the upper/lower pair that carries gradients.
    soft = bytes([40, 40, 40]) * 2 + bytes([44, 44, 44]) * 2
    (line,) = quadrant_lines(1, 1, soft)
    assert line.plain == "▀" and str(line.spans[0].style) == "#282828 on #2c2c2c"
    scene = render_landscape(120, 30).plain
    assert len({char for char in scene if char in QUADRANT_GLYPHS}) >= 5
