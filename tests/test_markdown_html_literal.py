"""Raw HTML in a model reply is shown literally, never stripped nor interpreted.

markdown-it classifies ``<script>``/``<b>`` as ``html_inline`` and a tag on its
own line as ``html_block``; both renderers (Rich's and ``selectable_markdown``)
used to drop those tokens silently, so ``<script>alert(1)</script>`` reached the
screen as ``alert(1)``. Fenced code keeps its HTML verbatim and unescaped.
"""
from rich.console import Console

from isycode.terminal_links import rich_markdown
from isycode.tui_copy import selectable_markdown

NESTED = ("> cita\n>> anidada\n\n***negrita cursiva*** ~~tachado~~ `inline` "
          "<script>alert(1)</script> <b>html</b>")


def _plain(source: str) -> str:
    return selectable_markdown(rich_markdown(source)).plain


def _rich_plain(source: str) -> str:
    # Rich's own renderer path (anything that renders the Markdown object directly).
    console = Console(width=200, color_system=None, legacy_windows=False, record=True)
    console.print(rich_markdown(source))
    return console.export_text()


def test_inline_html_tags_stay_visible_as_text():
    plain = _plain(NESTED)
    assert "<script>alert(1)</script>" in plain
    assert "<b>html</b>" in plain
    assert "alert(1)" in plain and "`inline`" not in plain  # inline code still parses
    assert "***negrita" not in plain  # markdown emphasis still parses


def test_rich_renderer_also_shows_inline_html_literally():
    plain = _rich_plain("a <b>bold</b> c\n\n<script>alert(1)</script>\n")
    assert "<b>bold</b>" in plain and "<script>alert(1)</script>" in plain


def test_html_block_is_kept_verbatim():
    block = "Texto\n\n<div class=\"x\">\n  bloque <b>si</b>\n</div>\n\nFin\n"
    plain = _plain(block)
    assert "<div class=\"x\">" in plain and "</div>" in plain and "bloque <b>si</b>" in plain
    assert plain.index("Texto") < plain.index("<div") < plain.index("Fin")


def test_html_inside_fences_is_untouched_and_unescaped():
    fenced = "```html\n<script>x < y</script>\n```\n\n`<i>inline</i>`\n"
    plain = _plain(fenced)
    assert "<script>x < y</script>" in plain
    assert "<i>inline</i>" in plain
    assert "&lt;" not in plain


def test_html_in_table_cells_stays_literal():
    table = "| a | b |\n|---|---|\n| <i>x</i> | <u>y</u> |\n"
    plain = _plain(table)
    assert "<i>x</i>" in plain and "<u>y</u>" in plain


def test_autolink_still_works_next_to_html():
    plain = _plain(" Mira https://example.com/x y <br> fin\n")
    assert "https://example.com/x" in plain and "<br>" in plain


def test_link_style_survives_html_escaping():
    text = selectable_markdown(rich_markdown("[sitio](https://example.com) <b>x</b>"))
    console = Console(record=True, width=120)
    segment = next(s for s in console.render(text) if s.text == "sitio")
    assert segment.style.link == "https://example.com"
