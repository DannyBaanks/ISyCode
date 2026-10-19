"""Colors, banner, and text helpers for the ISyCode TUI.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from textual.widgets import Static
from rich.text import Text
from rich.cells import cell_len
import json
from pathlib import Path
from isycode.localization import tr



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
                        style=f"bold {GREEN}" if enabled else MUTED)
    else:
        rendered.append("✓ " + tr("on") if enabled else "− " + tr("off"),
                        style=GREEN if enabled else MUTED)
    return rendered


# ── Accepted shared palette ─────────────────────────────────────
# Packaged export of the accepted authoring palette, shared by rich text and TCSS.
_PALETTE = json.loads((Path(__file__).with_name("assets") / "design-tokens.json").read_text())["colors"]
BG = BG2 = _PALETTE["surface"]
ACCENT = ACCENT2 = CYAN = _PALETTE["focus"]
TEXT, MUTED = _PALETTE["text"], _PALETTE["muted"]
GREEN, YELLOW, RED = _PALETTE["success"], _PALETTE["warning"], _PALETTE["error"]
SECURITY = _PALETTE["security"]


# ── High-contrast overrides (optional accessibility mode) ─────────
# Base controls already use the accepted black surface. Accessibility mode
# strengthens text and frames without adding another color family.
HIGH_CONTRAST_CSS = """
Screen { background: #000000; color: #ffffff; }
Input, TextArea, #prompt-input { color: #ffffff !important; }
Input:focus, TextArea:focus, #prompt-input:focus { border: solid #ffffff !important; }
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
        if lowered in {"completed", "exit 0", "allow"}:
            color = GREEN
        elif "denied" in lowered:
            # F-07: security-policy DENY is orange, distinct from operational
            # errors (RED) so a user can tell a policy denial from a failure.
            color = SECURITY
        elif any(word in lowered for word in ("failed", "error", "exit 1")):
            color = RED
        elif any(word in lowered for word in ("running", "checking", "missing", "unavailable", "rejected", "cancelled")):
            color = YELLOW
        elif index == 0:
            from isycode.operation_style import operation_color
            color = operation_color(part) or TEXT
        else:
            color = MUTED
        result.append(part, style=color)
    return result


def _fit_cells(text: str, width: int) -> str:
    """Keep one label inside a column without breaking a wide character."""
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    if width == 1:
        return "…"
    budget = width - 1
    kept = text[:budget]
    while kept and cell_len(kept) > budget:
        kept = kept[:-1]
    idx = len(kept)
    while idx < len(text) and cell_len(kept + text[idx]) <= budget:
        kept += text[idx]
        idx += 1
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


authority_capability_label = _authority_capability_label
semantic_box_title = _semantic_box_title
fit_cells = _fit_cells
elapsed_label = _elapsed_label
