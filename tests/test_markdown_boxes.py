"""Agent Markdown tables and drawn boxes render as aligned, width-bounded boxes."""
from rich.text import Text
from rich.cells import cell_len

from isycode import tui_theme
from isycode.terminal_links import fence_box_art, rich_markdown
from isycode.tui_copy import selectable_markdown

TABLE = """Intro

| Modelo | Estado | Nota |
|:--|:-:|--:|
| **Opus** | ✅ ok | 12 |
| Qwen 27B con un nombre muy largo que no cabe | ❌ falla | 3 |
| 日本語 | `x` | 100000 |
"""


def _box_lines(plain):
    return [line for line in plain.splitlines() if line and line[0] in "┌├│└+|"]


def test_table_is_an_aligned_box_that_fits_the_width():
    for width in (None, 80, 40):
        lines = _box_lines(selectable_markdown(rich_markdown(TABLE), width).plain)
        assert lines[0].startswith("┌") and lines[-1].startswith("└")
        widths = {cell_len(line) for line in lines}
        assert len(widths) == 1, (width, widths)  # emoji/CJK counted as 2 cells
        if width:
            assert widths.pop() <= width


def test_header_is_bold_and_alignment_is_kept():
    text = selectable_markdown(rich_markdown(TABLE), 80)
    plain = text.plain
    header = next(line for line in plain.splitlines() if "Modelo" in line)
    start = plain.index(header) + header.index("Modelo")
    assert any("bold" in str(span.style) and span.start <= start < span.end for span in text.spans)
    row = next(line for line in plain.splitlines() if "100000" in line)
    assert row.rstrip().endswith("100000 │")  # right-aligned column
    nota = next(line for line in plain.splitlines() if " 12 " in line)
    assert nota.rstrip().endswith("12 │")


def test_long_cell_wraps_inside_its_column():
    plain = selectable_markdown(rich_markdown(TABLE), 40).plain
    assert "Qwen 27B con un" in plain and "que no cabe" in plain
    assert all(cell_len(line) <= 40 for line in plain.splitlines())


def test_too_narrow_table_becomes_records():
    plain = selectable_markdown(rich_markdown(TABLE), 20).plain
    assert "┌" not in plain
    assert "Modelo: Opus" in plain and "Nota: 100000" in plain


def test_ascii_only_box(monkeypatch):
    monkeypatch.setattr(tui_theme, "_ASCII_ONLY", True)
    plain = selectable_markdown(rich_markdown(TABLE + "\n---\n"), 60).plain
    assert "┌" not in plain and "─" not in plain
    assert "+--" in plain and "| Opus" in plain


def test_rule_spans_the_width():
    plain = selectable_markdown(rich_markdown("a\n\n---\n\nb"), 50).plain
    assert "─" * 49 in plain


def test_drawn_boxes_in_prose_stay_verbatim_and_pipe_tables_stay_tables():
    art = "El flujo:\n┌────┐   ┌───┐\n│ *a* │──▶│ b_c │\n└────┘   └───┘\nfin\n"
    fenced = fence_box_art(art)
    assert "```text\n┌────┐" in fenced and "└───┘\n```\nfin" in fenced
    plain = selectable_markdown(rich_markdown(art), 60).plain
    assert "│ *a* │──▶│ b_c │" in plain
    ascii_box = "+----+\n|  x_y |\n+----+\n"
    assert fence_box_art(ascii_box).startswith("```text\n")
    pipe_table = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert fence_box_art(pipe_table) == pipe_table
    assert fence_box_art("A ─▶ B in prose") == "A ─▶ B in prose"
    already = "```\n┌──┐\n└──┘\n```\n"
    assert fence_box_art(already) == already


# ── CJK, fullwidth, ZWJ emoji and variation selectors: one cell measure everywhere ──
CJK_TABLE = ("| 名前 | 説明 | 絵文字 |\n|:--|:-:|--:|\n"
             "| 東京都 | 日本の首都で人口が非常に多い都市です | 🗼🍣 |\n"
             "| 北京 | 中华人民共和国的首都 | 🐉👨‍👩‍👧‍👦 |\n"
             "| Ⅻ | ｆｕｌｌｗｉｄｔｈ | 🏳️‍🌈 |\n")
WIDTHS = (None, 80, 60, 50, 44, 40, 36, 32, 30, 28)


def test_cjk_zwj_table_every_line_has_the_same_cell_width():
    # The right border │ must line up on every row: each box line measures the same
    # in Rich cells (what Textual uses to draw and pad), at every width.
    for width in WIDTHS:
        plain = selectable_markdown(rich_markdown(CJK_TABLE), width).plain
        lines = _box_lines(plain)
        assert lines[0].startswith("┌") and lines[-1].startswith("└")
        assert "名前" in plain and "Ⅻ" in plain
        # Every fullwidth letter survives (narrow widths wrap the word inside its column).
        assert all(ch in plain for ch in "ｆｕｌｌｗｉｄｔｈ"), (width, plain)
        widths = {cell_len(line) for line in lines}
        assert len(widths) == 1, (width, widths)
        if width:
            assert widths.pop() <= width, (width, widths)


def test_zwj_and_variation_sequences_are_measured_as_one_grapheme():
    # Consistent with Rich cell_len (what padding and borders use): a ZWJ family,
    # a VS16 flag, a skin tone and a regional-indicator flag each are 2 cells, never
    # the per-codepoint sum, and never start a wrapped line as an orphan.
    from rich.cells import split_graphemes
    from isycode.tui_copy import _widest_grapheme
    for glyph, expected in (("👨‍👩‍👧‍👦", 2), ("🏳️‍🌈", 2), ("👍🏽", 2), ("🇪🇸", 2), ("❤️", 2), ("名", 2), ("Ⅻ", 1)):
        spans, total = split_graphemes(glyph)
        assert total == expected == cell_len(glyph), glyph
        assert _widest_grapheme(Text(glyph)) == expected, glyph
    # Rich itself splits 🇪🇸 into two 1-cell halves; a flag is still one glyph and
    # must never be folded onto two lines, so its floor is the pair (2 cells).
    assert [size for _s, _e, size in split_graphemes("🇪🇸")[0]] == [1, 1]
    assert _widest_grapheme(Text("x 🇪🇸 y")) == 2
    assert _widest_grapheme(Text("🇪🇸🇫🇷")) == 4  # two flags side by side
    assert _widest_grapheme(Text("a🇪b🇸")) == 1   # separated indicators are not a flag


def test_zwj_table_never_loses_a_grapheme_or_leaves_an_orphan():
    for width in WIDTHS:
        text = selectable_markdown(rich_markdown(CJK_TABLE), width)
        plain = text.plain
        for glyph in ("🏳️‍🌈", "👨‍👩‍👧‍👦", "🗼🍣", "東京"):
            assert glyph in plain, (width, glyph)
        for line in plain.splitlines():
            assert not line.lstrip("│ ").startswith(("\u200d", "\ufe0f")), (width, line)


def test_column_width_never_below_its_widest_grapheme():
    # Even if _column_widths were to offer a 1-cell share, a column holding a
    # 2-cell grapheme keeps 2 cells: Text.wrap(fold) drops a grapheme wider than
    # the column instead of splitting it, which would silently lose content.
    from isycode.tui_copy import _column_widths
    # Narrow columns keep their natural width (they already hold the grapheme).
    assert _column_widths([2, 2, 60], 9) == [2, 2, 5]
    # A 2-cell floor in a column whose natural width is larger than its share:
    # the wide columns shrink, the emoji column never below 2.
    assert _column_widths([8, 8, 40], 20, [2, 2, 1]) == [7, 7, 6]
    # The floor only lifts a column that would otherwise fall below it, and the
    # cells it takes come from the widest remaining column; nothing is left over.
    assert _column_widths([30, 30], 10, [2, 2]) == [5, 5]
    assert _column_widths([30, 30], 10, [7, 2]) == [7, 3]
    assert _column_widths([10, 10, 10], 7, [2, 2, 2]) == [3, 2, 2]
    # Floors are never ignored for the natural width of a column that fits.
    assert _column_widths([2, 2, 60], 64, [2, 2, 1]) == [2, 2, 60]
    # Not enough room for every floor: hand out the floors; render_table_box
    # then falls back to records (checked in the test below).
    assert _column_widths([9, 9, 9], 5, [2, 2, 2]) == [2, 2, 2]
    assert _column_widths([9, 9], 3, [2, 2]) == [2, 2]
    assert _column_widths([1, 9], 3, [2, 2]) == [1, 2]  # natural 1 below floor 2: floor wins


def test_regional_flag_is_never_folded_onto_two_lines():
    # Rich measures 🇪🇸 as two 1-cell graphemes, so a 1-cell column would fold it
    # into 🇪 / 🇸 on separate lines. The floor keeps the column at 2 cells or the
    # table falls back to records; the flag always stays whole.
    from rich.text import Text
    from isycode.tui_copy import render_table_box
    md = "| a | b | c | d |\n|---|---|---|---|\n" \
         "| 🇪🇸 | 🇪🇸🇫🇷 | 🇪🇸 | " + "x" * 120 + " |\n"
    for width in (None, 60, 50, 44, 40, 36, 32, 30, 28, 24, 20):
        plain = selectable_markdown(rich_markdown(md), width).plain
        for line in plain.splitlines():
            assert not line.rstrip().endswith("🇪"), (width, line)
            assert not line.lstrip("│ ").startswith("🇸"), (width, line)
        if "┌" in plain:
            assert all("🇪🇸" in line or "🇫🇷" not in line for line in plain.splitlines()), (width, plain)
    # Direct: the floor refuses a 1-cell column even when the caller insists.
    rows = [(True, [Text("a"), Text("b"), Text("c")], [None] * 3),
            (False, [Text("🇪🇸"), Text("xy"), Text("lorem ipsum dolor sit amet consectetur")], [None] * 3)]
    assert "🇪" not in render_table_box(rows, 20).plain.rstrip("\n").splitlines()[-1]  # records, no box


def test_wide_grapheme_in_a_narrow_table_stays_visible():
    md = "| a | b |\n|---|---|\n| 👨‍👩‍👧‍👦 | x |\n| 🏳️‍🌈 | y |\n"
    for width in (None, 30, 20, 16):
        plain = selectable_markdown(rich_markdown(md), width).plain
        assert "👨‍👩‍👧‍👦" in plain and "🏳️‍🌈" in plain, (width, plain)
