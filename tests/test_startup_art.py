"""The startup landscape stays legible at terminal widths without image support."""

from rich.cells import cell_len

from isycode.startup_art import LANDSCAPE_PATH, SCENE_WIDTH, render_landscape, source_lines


def test_checked_in_scene_is_a_colored_braille_landscape():
    lines = source_lines()
    assert len(lines) == 18
    assert all(len(line) == SCENE_WIDTH for line in lines)
    assert lines == tuple(LANDSCAPE_PATH.read_text(encoding="utf-8").splitlines())
    assert "ISYCODE" in lines[1]
    assert any("\u2800" <= char <= "\u28ff" for line in lines for char in line)
    assert "╱" not in "\n".join(lines)
    assert "(=^.^=)" not in "\n".join(lines)
    styles = {str(span.style) for span in render_landscape(SCENE_WIDTH)._spans}
    assert len(styles) >= 8


def test_landscape_centers_and_crops_without_wrapping():
    for width in (24, 42, 60, 76, 90):
        lines = render_landscape(width).plain.splitlines()
        assert all(cell_len(line) == width for line in lines)
        assert any("ISYCODE" in line for line in lines)
    source = source_lines()[0]
    wide = render_landscape(90).plain.splitlines()[0]
    assert len(wide) - len(wide.lstrip(" ")) > len(source) - len(source.lstrip(" "))
