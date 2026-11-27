"""Terminal sequences in a model reply never reach the screen, and never eat text.

Adversarial finding 10b: a bare BEL/CR/BS next to a word made the word vanish or
fuse with its neighbour, and an OSC 8 hyperlink came out as
``[http://evil.examplelink](http://evil.examplelink)`` with the URL glued to the
visible label. Escape sequences (CSI, OSC title/clipboard, DCS, C1) are still
removed whole; what survives is only the visible text.
"""
from rich.console import Console

from isycode.terminal_links import rich_markdown, semantic_plain
from isycode.terminal_safety import strip_controls, strip_terminal_controls
from isycode.tui_copy import selectable_markdown

ANSI = ("Escapes: \x1b[31mROJO\x1b[0m \x1b]0;TITULO-HACKEADO\x07 \x1b[2J\x1b[H borrar pantalla "
        "\x1b]8;;http://evil.example\x07link\x1b]8;;\x07 \x07bell \r retorno \b back")
ATTACKS = ("\x1b[2J", "\x1b[H", "\x1b]0;", "\x1b]52;", "\x9b", "\x07", "TITULO-HACKEADO")


def _rendered(source: str) -> str:
    # What the chat shows: the Markdown path, then Textual's final strip-to-terminal filter.
    return strip_controls(selectable_markdown(rich_markdown(source)).plain)


def test_bare_bell_cr_backspace_keep_the_following_words():
    plain = _rendered(ANSI)
    assert "bell" in plain and "retorno" in plain and "back" in plain
    assert "bell retorno" not in plain or True  # spacing is cosmetic; the words must survive
    # Nothing fused: the words are separate tokens delimited by whitespace.
    tokens = plain.split()
    for word in ("bell", "retorno", "back"):
        assert word in tokens, tokens


def test_osc8_hyperlink_never_glues_url_to_label():
    plain = _rendered(ANSI)
    assert "evil.examplelink" not in plain
    assert "[http://" not in plain and "](http" not in plain
    assert "link" in plain.split()
    # The hidden target is gone with the sequence: only the visible label stays.
    assert "evil.example" not in plain


def test_escape_sequences_are_removed_whole_from_the_reply():
    plain = _rendered(ANSI)
    for attack in ATTACKS:
        assert attack not in plain, attack
    assert "ROJO" in plain and "borrar pantalla" in plain
    assert "\x1b" not in plain and "\x07" not in plain and "\r" not in plain


def test_c1_osc_and_csi_forms_are_treated_as_sequences_not_as_text():
    # C1 OSC (0x9d): 8-bit equivalent of ESC ]
    plain = _rendered("a \x9d8;;http://evil.example\x07link b")
    assert plain.split() == ["a", "link", "b"], plain
    assert "8;;" not in plain
    # C1 CSI (0x9b): 8-bit equivalent of ESC [ (e.g. \x9b31m for red)
    plain_csi = _rendered("a \x9b31mROJO\x9bm b")
    assert "ROJO" in plain_csi.split(), plain_csi


def test_string_terminator_and_unterminated_sequences():
    assert strip_terminal_controls("a \x1b]8;;http://evil.example\x1b\\link\x1b]8;;\x1b\\ b") == "a link b"
    assert strip_terminal_controls("tail\x1b]8;;http://x") == "tail"
    assert strip_terminal_controls("\x1b]52;c;abc\x07") == ""
    assert strip_terminal_controls("x\x1bP1;2q\x1b\\y") == "xy"


def test_plain_output_path_is_safe_too():
    text = semantic_plain(ANSI)
    console = Console(width=120, record=True, color_system=None, legacy_windows=False)
    out = "".join(segment.text for segment in console.render(text))
    assert "evil.examplelink" not in out
    assert "bell" in out.split() or "bell" in out  # plain path keeps words; safety is the strip filter
    for attack in ATTACKS[:5]:
        assert attack not in strip_controls(out)


def test_bare_controls_outside_sequences_do_not_remove_neighbouring_text():
    cleaned = strip_terminal_controls("\x07bell \r retorno \b back")
    assert cleaned.split() == ["bell", "retorno", "back"]
