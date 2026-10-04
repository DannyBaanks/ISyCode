"""The startup village fills the chat width without image support."""

from rich.cells import cell_len

from isycode.startup_art import RASTER_PATH, render_landscape, source_size
from isycode.terminal_art import decode_raster


def test_checked_in_village_is_the_lighthouse_picture():
    assert source_size() == (1152, 768)
    width, height, rgb = decode_raster(RASTER_PATH.read_bytes())
    assert (width, height) == (1152, 768)

    def pixel(x, y):
        start = (y * width + x) * 3
        return tuple(rgb[start:start + 3])

    lamp = pixel(558, 84)
    glow = pixel(546, 74)
    sky = pixel(40, 30)
    assert min(lamp) > 240
    assert glow[0] > glow[2] + 40
    assert max(sky) < 80


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

    capped = render_landscape(180).plain.splitlines()
    assert len(capped) <= 30
    assert all(cell_len(line) == 180 for line in capped)
    assert capped[0].startswith(" ")
    assert "▀" in capped[len(capped) // 2]
    assert "╱" not in "\n".join(capped)

    short = render_landscape(160, max_rows=12).plain.splitlines()
    assert len(short) <= 12
    assert all(cell_len(line) == 160 for line in short)
    styles = {str(span.style) for span in render_landscape(90)._spans}
    assert len(styles) >= 8
