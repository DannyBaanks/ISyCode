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


def test_landscape_fills_the_chat_width_and_keeps_its_proportions():
    narrow = render_landscape(24).plain.splitlines()
    assert all(cell_len(line) == 24 for line in narrow)
    assert any("ISYCODE" in line for line in narrow)
    assert "▀" not in "\n".join(narrow)

    for width in (42, 60, 76, 90, 120):
        rendered = render_landscape(width)
        lines = rendered.plain.splitlines()
        assert lines
        assert all(cell_len(line) == width for line in lines)
        assert all("▀" in line for line in lines)
        assert len(lines) == max(1, round(width * 768 / (2 * 1152)))
        assert "╱" not in rendered.plain
    styles = {str(span.style) for span in render_landscape(90)._spans}
    assert len(styles) >= 8
