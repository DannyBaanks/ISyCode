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


def test_sleeping_cat_sits_beside_the_caption_with_z_on_its_face():
    from isycode.cat_activity import sleeping_cat
    for width in (10, 14, 24, 30):
        rows = sleeping_cat(width).plain.splitlines()
        assert len(rows) == 3
        assert all(cell_len(row) == width for row in rows)
        assert rows[2].startswith("Chat ready")
        assert sleeping_cat(width).plain == sleeping_cat(width).plain
    for width in (14, 24, 30):
        rows = sleeping_cat(width).plain.splitlines()
        face = rows[1]
        z_at = face.index("z")
        braille = [i for i, char in enumerate(face) if "\u2800" < char <= "\u28ff"]
        assert braille and z_at == braille[0] - 1
        assert "z" not in face[braille[-1] + 1:]
        assert not rows[2].rstrip().endswith("z")
        tail = [i for i, char in enumerate(rows[2]) if "\u2800" < char <= "\u28ff"]
        assert tail and tail[0] > len("Chat ready")
    wide = sleeping_cat(30).plain.splitlines()
    face_ink = [i for i, char in enumerate(wide[1]) if "\u2800" < char <= "\u28ff"]
    tail_ink = [i for i, char in enumerate(wide[2]) if "\u2800" < char <= "\u28ff"]
    assert tail_ink[-1] > face_ink[-1]


def test_cat_uses_fine_dots_instead_of_solid_block_pixels():
    from isycode.cat_activity import sleeping_cat
    for drawing in (walking_cat(30, 1), sleeping_cat(30)):
        assert any("\u2801" <= char <= "\u28ff" for char in drawing.plain)
        assert not any("\u2580" <= char <= "\u259f" for char in drawing.plain)
