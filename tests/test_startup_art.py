"""The startup village is a fixed drawing, centered, and never scaled up."""

from rich.cells import cell_len

from isycode.startup_art import MAX_SCENE_ROWS, RASTER_PATH, render_landscape, source_size
from isycode.terminal_art import decode_raster


def test_checked_in_village_is_the_lighthouse_picture():
    assert MAX_SCENE_ROWS == 36
    assert source_size() == (108, 72)
    width, height, rgb = decode_raster(RASTER_PATH.read_bytes())
    assert (width, height) == (108, 72)
    assert height // 2 == MAX_SCENE_ROWS

    def pixel(x, y):
        start = (y * width + x) * 3
        return tuple(rgb[start:start + 3])

    assert pixel(54, 19) == (255, 255, 255)
    assert min(pixel(93, 9)) > 220
    assert max(pixel(4, 4)) < 40
    glow = pixel(20, 51)
    assert glow[0] > glow[2] + 40
    assert max(pixel(60, 70)) < 40


def test_landscape_keeps_the_whole_village_on_screen():
    narrow = render_landscape(24).plain.splitlines()
    assert all(cell_len(line) == 24 for line in narrow)
    assert any("ISYCODE" in line for line in narrow)
    assert "▀" not in "\n".join(narrow)

    fitted = render_landscape(90, max_rows=40)
    fitted_lines = fitted.plain.splitlines()
    assert len(fitted_lines) == 30
    assert all(cell_len(line) == 90 for line in fitted_lines)
    assert all(line.startswith("▀") for line in fitted_lines)

    wide = render_landscape(180).plain.splitlines()
    assert len(wide) == 36
    assert all(cell_len(line) == 180 for line in wide)
    assert wide[0].startswith(" " * 36)
    middle = wide[len(wide) // 2]
    assert middle.count("▀") == 108
    assert "╱" not in "\n".join(wide)

    short = render_landscape(160, max_rows=12).plain.splitlines()
    assert len(short) <= 12
    assert all(cell_len(line) == 160 for line in short)
    styles = {str(span.style) for span in render_landscape(90)._spans}
    assert len(styles) >= 8
