"""The startup landscape stays legible at terminal widths without image support."""

from rich.cells import cell_len

from isycode.startup_art import SCENE_WIDTH, render_landscape, source_lines


def test_checked_in_glyphfuck_scene_is_rectangular_and_contains_wordmark():
    lines = source_lines()
    assert len(lines) == 18
    assert all(len(line) == SCENE_WIDTH for line in lines)
    assert "#####" in "\n".join(lines)
    assert ".--." in "\n".join(lines)


def test_landscape_centers_and_crops_without_wrapping():
    for width in (24, 42, 60, 76, 90):
        lines = render_landscape(width).plain.splitlines()
        assert all(cell_len(line) == width for line in lines)
        assert any("ISYCODE" in line or "#####" in line for line in lines)
    wide = render_landscape(90).plain.splitlines()
    assert wide[0].index(".") > source_lines()[0].index(".")
