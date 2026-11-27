"""Agent Markdown tables and drawn boxes render as aligned, width-bounded boxes."""
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
