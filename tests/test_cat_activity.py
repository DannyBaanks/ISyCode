from rich.cells import cell_len
from isycode.cat_activity import walking_cat


def test_cat_fits_and_bounces_inside_fixed_brackets():
    for width in (10, 12, 20, 30):
        travel = width - 10
        for tick in range(max(4, travel * 4)):
            rows = walking_cat(width, tick).plain.splitlines()
            assert len(rows) == 3
            assert all(cell_len(row) == width for row in rows)
            assert rows[1][0] == "[" and rows[1][-1] == "]"
        if travel:
            assert walking_cat(width, 0).plain.splitlines()[1].index(next(c for c in walking_cat(width, 0).plain.splitlines()[1] if "\u2801" <= c <= "\u28ff")) < walking_cat(width, travel).plain.splitlines()[1].index(next(c for c in walking_cat(width, travel).plain.splitlines()[1] if "\u2801" <= c <= "\u28ff"))
            assert walking_cat(width, 0).plain == walking_cat(width, travel * 2).plain


def test_tiny_cat_fallback_stays_bounded():
    for width in range(1, 10):
        assert cell_len(walking_cat(width, 0).plain) == width


def test_sleeping_cat_is_static_and_keeps_ready_explicit():
    from isycode.cat_activity import sleeping_cat
    for width in (10, 14, 24, 30):
        rows = sleeping_cat(width).plain.splitlines()
        assert all(cell_len(row) == width for row in rows)
        assert "z" in rows[0]
        assert rows[1].startswith("[") and rows[1].endswith("]")
        assert "Chat ready" in rows[2]
        assert sleeping_cat(width).plain == sleeping_cat(width).plain


def test_cat_uses_fine_dots_instead_of_solid_block_pixels():
    from isycode.cat_activity import sleeping_cat
    for drawing in (walking_cat(30, 1), sleeping_cat(30)):
        assert any("\u2801" <= char <= "\u28ff" for char in drawing.plain)
        assert not any("\u2580" <= char <= "\u259f" for char in drawing.plain)
