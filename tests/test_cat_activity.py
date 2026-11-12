from rich.cells import cell_len
from isycode.cat_activity import sleeping_cat, walk_period, walking_cat


def _ink(row):
    return [i for i, char in enumerate(row) if "\u2800" < char <= "\u28ff"]


def test_cat_fits_and_bounces_inside_fixed_brackets():
    for width in (10, 12, 13, 20, 30, 37):
        period = walk_period(width)
        for tick in range(period + 2):
            rows = walking_cat(width, tick).plain.splitlines()
            assert len(rows) == 3
            assert all(cell_len(row) == width for row in rows)
            assert rows[1][0] == "[" and rows[1][-1] == "]"
            assert all(1 <= i <= width - 2 for row in rows for i in _ink(row))
        assert walking_cat(width, 0).plain == walking_cat(width, period).plain
        if width > 10:
            first = min(i for row in walking_cat(width, 0).plain.splitlines() for i in _ink(row))
            far = max(i for row in walking_cat(width, period // 2 - 1).plain.splitlines() for i in _ink(row))
            assert first == 1 and far >= width - 3


def test_cat_advances_one_dot_per_tick_instead_of_jumping_a_cell():
    width = 30
    travel = (width - 10) * 2
    frames = [walking_cat(width, tick).plain for tick in range(travel)]
    assert all(a != b for a, b in zip(frames, frames[1:]))
    starts = [min(i for row in frame.splitlines() for i in _ink(row)) for frame in frames]
    assert all(0 <= b - a <= 1 for a, b in zip(starts, starts[1:]))
    assert starts[-1] - starts[0] >= width - 12


def test_cat_stops_blinks_and_turns_round_at_the_end_of_the_track():
    width = 20
    travel = (width - 10) * 2
    pause = [walking_cat(width, tick).plain for tick in range(travel, walk_period(width) // 2)]
    assert len(pause) >= 4
    assert len(set(pause)) > 1, "the blink is visible while the cat stands still"
    starts = {min(i for row in frame.splitlines() for i in _ink(row)) for frame in pause}
    assert len(starts) == 1
    back = walking_cat(width, walk_period(width) // 2 + 4).plain
    assert max(i for row in back.splitlines() for i in _ink(row)) < width - 2


def test_tiny_cat_fallback_stays_bounded():
    for width in range(1, 10):
        assert cell_len(walking_cat(width, 0).plain) == width


def test_ascii_only_cat_uses_no_unicode_drawing():
    for width in (4, 10, 14, 30):
        for tick in range(40):
            drawing = walking_cat(width, tick, ascii_only=True).plain
            assert drawing.isascii()
            assert all(cell_len(row) == width for row in drawing.splitlines())
    assert "=^.^=" in walking_cat(14, 0, ascii_only=True).plain
    assert walking_cat(14, 0, ascii_only=True).plain != walking_cat(14, 6, ascii_only=True).plain
    for width in (10, 14, 30):
        rows = sleeping_cat(width, ascii_only=True).plain.splitlines()
        assert len(rows) == 3 and all(row.isascii() and cell_len(row) == width for row in rows)
        assert rows[2].startswith("Chat ready")


def test_sleeping_cat_sits_beside_the_caption_with_z_on_its_face():
    for width in (10, 14, 24, 30):
        rows = sleeping_cat(width).plain.splitlines()
        assert len(rows) == 3
        assert all(cell_len(row) == width for row in rows)
        assert rows[2].startswith("Chat ready")
        assert sleeping_cat(width).plain == sleeping_cat(width).plain
    for width in (24, 30):
        rows = sleeping_cat(width).plain.splitlines()
        face = rows[1]
        z_at = face.index("z")
        braille = _ink(face)
        assert braille and 1 <= braille[0] - z_at <= 2
        assert "z" not in face[braille[-1] + 1:]
        assert not rows[2].rstrip().endswith("z")
        tail = _ink(rows[2])
        assert tail and tail[0] > len("Chat ready")
    wide = sleeping_cat(30).plain.splitlines()
    assert _ink(wide[2])[-1] > _ink(wide[1])[-1]


def test_narrow_column_keeps_a_whole_cat_above_its_caption():
    """No clipped piece of a cat beside the words: the animal lies on the caption line."""
    for width in range(10, 20):
        rows = sleeping_cat(width).plain.splitlines()
        assert len(rows) == 3 and all(cell_len(row) == width for row in rows)
        assert rows[2].rstrip() == "Chat ready"
        assert not _ink(rows[2])
        ink = [_ink(row) for row in rows[:2]]
        assert all(ink) and min(map(min, ink)) == 0 and max(map(max, ink)) == 8
    assert "z" in sleeping_cat(13).plain.splitlines()[0]


def test_cat_uses_fine_dots_instead_of_solid_block_pixels():
    for width in (13, 30):
        for tick in range(walk_period(width)):
            drawing = walking_cat(width, tick)
            assert any("\u2801" <= char <= "\u28ff" for char in drawing.plain)
            assert "\u28ff" not in drawing.plain
            assert not any("\u2580" <= char <= "\u259f" for char in drawing.plain)
    for width in (13, 30):
        assert "\u28ff" not in sleeping_cat(width).plain
        assert not any("\u2580" <= char <= "\u259f" for char in sleeping_cat(width).plain)
    assert walking_cat(30, 0).plain != walking_cat(30, 1).plain


def test_long_caption_wraps_inside_the_activity_column():
    label = "Interrupted · inspect the transcript before retrying"
    for width in (16, 28, 40):
        rows = sleeping_cat(width, label).plain.splitlines()
        assert len(rows) == 3
        assert all(cell_len(row) == width for row in rows)
        assert rows[0].lstrip().startswith("Interrupted")
        assert "Interrupted" in sleeping_cat(width, label).plain
        if width >= 28:
            assert "retrying" in sleeping_cat(width, label).plain


def test_resting_cat_fills_all_three_rows_when_the_column_has_room():
    rows = sleeping_cat(24).plain.splitlines()
    ink = [_ink(row) for row in rows]
    assert all(ink), "ears, body and tail each get a row"
    assert all(i > len("Chat ready") for row in ink for i in row)


def test_sleep_symbols_climb_away_from_the_face_without_widening_track():
    rows = sleeping_cat(30).plain.splitlines()
    positions = [row.index('z') for row in rows]
    assert positions[0] == positions[1] + 1 == positions[2] + 2
    assert all(row.count('z') == 1 and cell_len(row) == 30 for row in rows)
