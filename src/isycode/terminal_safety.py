"""Nothing shown on screen can send its own terminal control sequences.

Model replies, file contents, tool and MCP results, command output and
provider errors are untrusted text. If an ESC or C1 control character from
them reaches the terminal, the text can clear the screen, retitle the window,
move the cursor or, through OSC 52, write the user's clipboard. Textual
renders every on-screen strip through ``Strip.render``; this module wraps that
one place so the text of each segment loses its C0, DEL and C1 control
characters before Textual adds its own styling sequences around it.

Control characters have zero cell width (``rich.cells.cell_len``), so removing
them leaves layout untouched. Textual's own cursor moves and styles are not
segment text and are unaffected. If Textual's internals change shape, the
install refuses (fail closed) instead of rendering unfiltered text.
"""
from __future__ import annotations

# C0 (0x00-0x1F, newline and tab included: a strip is one screen row), DEL, C1.
_CONTROLS = dict.fromkeys([*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0)])


def strip_controls(text: str) -> str:
    """``text`` without terminal control characters."""
    return text.translate(_CONTROLS)


def install() -> None:
    """Filter segment text at Textual's single strip-to-terminal step. Idempotent."""
    from rich.color import ColorSystem
    from textual.strip import Strip

    if getattr(Strip.render, "_isycode_safe", False):
        return
    if not all(hasattr(Strip, name) for name in ("render", "render_style")) \
            or "_render_cache" not in getattr(Strip, "__slots__", ("_render_cache",)):
        raise RuntimeError("Textual's Strip changed; refusing to render unfiltered text")

    def render(self, console) -> str:
        if self._render_cache is None:
            color_system = console._color_system or ColorSystem.TRUECOLOR
            style_text = self.render_style
            self._render_cache = "".join(
                strip_controls(text) if style is None
                else style_text(style, strip_controls(text), color_system=color_system)
                for text, style, _ in self._segments)
        return self._render_cache

    render._isycode_safe = True
    render.__doc__ = Strip.render.__doc__
    Strip.render = render


__all__ = ["install", "strip_controls"]
