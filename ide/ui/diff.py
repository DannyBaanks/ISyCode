"""Diff rendering for the ISyCode editor using central theme palette."""

from __future__ import annotations

import difflib
import html

from . import theme

_CSS = f"""
<style>
body {{
    background-color: {theme.SURFACE};
    color: {theme.TEXT};
    font-family: {theme.MONO};
    font-size: 12px;
    margin: 4px;
}}
.diff-add {{
    background-color: {theme.DIFF_ADD_BG};
    color: {theme.DIFF_ADD_FG};
    padding: 1px 4px;
    border-radius: 2px;
}}
.diff-del {{
    background-color: {theme.DIFF_DEL_BG};
    color: {theme.DIFF_DEL_FG};
    padding: 1px 4px;
    border-radius: 2px;
}}
.diff-hdr {{
    color: {theme.DIFF_HDR_FG};
    font-weight: bold;
    padding: 2px 4px;
}}
.diff-ctx {{
    color: {theme.DIFF_CTX_FG};
    padding: 1px 4px;
}}
.empty {{
    color: {theme.TEXT_FAINT};
    font-style: italic;
}}
</style>
"""


def render_diff(old_text: str, new_text: str, context: int = 3) -> str:
    """Return an HTML fragment coloring a unified diff of two texts."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = difflib.unified_diff(old_lines, new_lines, fromfile="saved",
                                tofile="current", lineterm="", n=context)
    blocks = []
    for line in diff:
        escaped = html.escape(line)
        if line.startswith("+") and not line.startswith("+++"):
            blocks.append(f'<div class="diff-add">{escaped}</div>')
        elif line.startswith("-") and not line.startswith("---"):
            blocks.append(f'<div class="diff-del">{escaped}</div>')
        elif line.startswith("@@"):
            blocks.append(f'<div class="diff-hdr">{escaped}</div>')
        else:
            blocks.append(f'<div class="diff-ctx">{escaped}</div>')
    return _CSS + "".join(blocks) if blocks else f'{_CSS}<div class="empty">(no changes)</div>'


def has_changes(old_text: str, new_text: str) -> bool:
    return old_text != new_text