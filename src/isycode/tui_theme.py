"""Colors, banner, and text helpers for the ISyCode TUI.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from textual.widgets import Static
from rich.text import Text
from rich.cells import cell_len



_ASCII_ONLY = False


def set_ascii_only(enabled: bool) -> None:
    """Switch state glyphs to plain ASCII for terminals without Unicode."""
    global _ASCII_ONLY
    _ASCII_ONLY = bool(enabled)


def ascii_only() -> bool:
    return _ASCII_ONLY


def _authority_capability_label(label: str, enabled: bool) -> Text:
    """Render an understandable permission state without exposing policy internals."""
    rendered = Text(label + "  ")
    if _ASCII_ONLY:
        rendered.append("[ON]" if enabled else "[OFF]",
                        style="bold #00ff00" if enabled else "bold #ff0000")
    else:
        rendered.append("● ON" if enabled else "● OFF",
                        style="bold #00ff00" if enabled else "bold #ff0000")
    return rendered


# ── Palette (Crush-inspired but softer) ───────────────────────────
BG = "#1a1a2e"        # deep navy-black
BG2 = "#292a2e"       # graphite rail background
ACCENT = "#e94560"    # crush pink-red (softened)
ACCENT2 = "#9b5de5"   # purple accent
TEXT = "#e0e0e0"      # main text
MUTED = "#9aa3ad"     # secondary text, readable on the dark surface
GREEN = "#4ade80"     # success / granted
YELLOW = "#fbbf24"    # warning / plan
RED = "#f87171"       # error / denied
CYAN = "#22d3ee"      # info / host


# ── High-contrast overrides (optional accessibility mode) ─────────
# The semantic palette above already clears WCAG AA on pure black
# (TEXT 13.7:1, MUTED 8.5:1, GREEN 10.8:1, YELLOW 11.6:1, RED 5.9:1),
# so only the control surfaces and borders need restyling. Injected as
# an extra stylesheet source at runtime; never mutates the base CSS.
HIGH_CONTRAST_CSS = """
Screen { background: #000000; color: #ffffff; }
#banner { background: #000000; }
#chat { background: #000000; }
#command-bar { background: #000000; }
#command-bar Button { background: #000000; }
Footer { background: #000000; color: #9aa3ad; }
Input { background: #000000; color: #ffffff; border: round #9aa3ad; }
Input:focus { background: #000000; border: round #ffffff; }
TextArea { background: #000000; border: round #9aa3ad; }
TextArea:focus { border: round #ffffff; }
#prompt-input { background: #000000; color: #ffffff; border: round #9aa3ad; }
#prompt-input:focus { background: #000000; border: round #ffffff; }
ModalScreen Button { background: #1a1a1a; color: #ffffff; }
ModalScreen Button:hover { background: #2a2a2a; }
ModalScreen Button:focus { background: #3a3a3a; text-style: bold; }
ModalScreen Button.-primary { background: #7650a1; color: #ffffff; }
#side-panel { background: #000000; border: round #9aa3ad; }
#rail-card { background: #000000; border: round #9aa3ad; }
#workspace-tree { background: #000000; border: round #9aa3ad; }
#file-preview-scroll { background: #000000; border: round #9aa3ad; }
#rail-tabs { border: round #9aa3ad; }
#idea-box { background: #000000; border: round #9aa3ad; }
#shell-box { background: #000000; border: round #9aa3ad; }
#queued-box { background: #000000; }
#agent-tasks { background: #000000; border-top: solid #9aa3ad; }
#slash-suggestions { background: #000000; border: round #9aa3ad; }
#action-card { background: #000000; border: round #9aa3ad; }
.tool-activity { background: #000000; }
.external-review { background: #000000; border: round #9aa3ad; }
.user-turn { background: #000000; }
ThoughtBlock { border: round #9aa3ad; }
"""


# ── Banner: literal, exact. Spells ISYCODE. ──────────────────────
BANNER = r"""
 ██╗███████╗██╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗
 ██║██╔════╝╚██╗ ██╔╝██╔════╝██╔═══██╗██╔══██╗██╔════╝
 ██║███████╗ ╚████╔╝ ██║     ██║   ██║██║  ██║█████╗
 ██║╚════██║  ╚██╔╝  ██║     ██║   ██║██║  ██║██╔══╝
 ██║███████║   ██║   ╚██████╗╚██████╔╝██████╔╝███████╗
 ╚═╝╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝
"""


def banner_text() -> Text:
    """Crush-style banner: bold letters with diagonal hatch."""
    t = Text()
    if _ASCII_ONLY:
        t.append("ISYCODE\n", style="bold #e94560")
        t.append("  One AI. Many hosts. One capability fabric.", style="italic #6c757d")
        return t
    for line in BANNER.strip("\n").split("\n"):
        t.append(line + "\n", style="bold #e94560")
    t.append("\n  One AI. Many hosts. One capability fabric.", style="italic #6c757d")
    return t


def status_phrase(text: str) -> str:
    """Title-case a short status chip.

    PATH, MCPs, ISyCode, and counts such as 1/2 stay as written. Do not pass
    skill slugs, server ids, or paths through this.
    """
    pieces = []
    for token in str(text).split(" "):
        letters = "".join(character for character in token if character.isalpha())
        if (
            not letters
            or letters.isupper()
            or any(character.isupper() for character in letters[1:])
            or any(character.isdigit() for character in token)
        ):
            pieces.append(token)
            continue
        pieces.append(token[0].upper() + token[1:].lower())
    return " ".join(pieces)


def switch_row(on: bool | None, name: str, note: str = "", *, inactive: bool = False) -> Text:
    """A colored mark and a name. The row itself stays unfilled.

    ON and OFF use distinct glyphs (✓ / ✗), not just green/red, so the state
    survives a monochrome terminal and red-green colour blindness. The rail
    deliberately carries no "ON"/"OFF" text (see test_side_panel), so the glyph
    is the only non-colour cue. ``inactive`` (○) and ``None`` (···) stay distinct.
    """
    row = Text()
    if inactive:
        row.append("[-] " if _ASCII_ONLY else "○ ", style=MUTED)
    elif on is None:
        row.append("... " if _ASCII_ONLY else "··· ", style=f"bold {YELLOW}")
    elif on:
        row.append("[x] " if _ASCII_ONLY else "✓ ", style=f"bold {GREEN}")
    else:
        row.append("[ ] " if _ASCII_ONLY else "✗ ", style=f"bold {RED}")
    row.append(name, style=f"bold {TEXT}")
    if note:
        row.append(f"\n  {note}", style=MUTED)
    return row


def switch_rows(rows: list[Text]) -> Text:
    return Text("\n").join(rows)


def _semantic_box_title(title: str) -> Text:
    result = Text()
    for index, part in enumerate(str(title).split(" · ")):
        if index:
            result.append(" · ", style=MUTED)
        lowered = part.casefold()
        if lowered in {"ready", "completed", "exit 0", "allow"}:
            color = GREEN
        elif any(word in lowered for word in ("denied", "failed", "error", "exit 1")):
            color = RED
        elif any(word in lowered for word in ("running", "checking", "missing", "unavailable", "rejected", "cancelled")):
            color = YELLOW
        elif index == 0:
            from isycode.operation_style import operation_color
            color = operation_color(part) or ("bold #c7b8d4" if "thinking" in lowered or "thought" in lowered else TEXT)
        else:
            color = MUTED
        result.append(part, style=color)
    return result


def _fit_cells(text: str, width: int) -> str:
    """Keep one label inside a column without breaking a wide character."""
    if width <= 0 or cell_len(text) <= width:
        return text
    if width == 1:
        return "…"
    kept = text
    while kept and cell_len(kept) > width - 1:
        kept = kept[:-1]
    return kept + "…"


def _elapsed_label(seconds: float) -> str:
    """Format elapsed wall time compactly for live activity labels."""
    if seconds < 1:
        return "<1s"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def static_content(widget: Static):
    """What a Static shows: ``renderable`` before Textual 2, ``content`` after."""
    content = getattr(widget, "renderable", None)
    if content is None:
        content = getattr(widget, "content", "")
    if isinstance(content, (str, Text)) or hasattr(content, "__rich_console__") \
            or hasattr(content, "__rich__"):
        return content
    return getattr(content, "plain", str(content))


def plain_text(widget: Static) -> str:
    content = static_content(widget)
    return content if isinstance(content, str) else getattr(content, "plain", str(content))
