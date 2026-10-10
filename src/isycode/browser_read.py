"""Reduce Playwright accessibility snapshots to bounded, untrusted page text."""
from __future__ import annotations

import json
import re
import unicodedata

MAX_BROWSER_TEXT = 24_000
_NODE = re.compile(r"^(?P<indent>\s*)-\s+(?P<role>[a-z][a-z0-9_-]*)(?P<rest>.*)$")
_LABEL = re.compile(r'"((?:\\.|[^"\\])*)"')
_SKIP_SUBTREES = frozenset({
    "banner", "navigation", "contentinfo", "dialog", "search", "form",
    "toolbar", "menu", "menuitem", "tablist", "tab", "button", "textbox",
    "combobox", "checkbox", "radio", "img", "image", "separator",
})
_TEXT_ROLES = frozenset({
    "heading", "paragraph", "text", "listitem", "link", "generic", "term",
    "definition", "blockquote", "code", "strong", "emphasis",
})
_SKIP_UI_LABEL = re.compile(
    r"^(?:skip|jump) to (?:main )?(?:content|search)"
    r"|accessibility links"
    r"|keyboard shortcuts for audio player"
    r"|subscribe(?: to)?"
    r"|you must be signed in to .+"
    r"|(?:fork|star)(?: \([\d.,]+[kKmM]?\))?"
    r"|(?:repository )?navigation$",
    re.IGNORECASE,
)


def _plain_text(value: str) -> str:
    # Private-use glyphs are common icon-font artifacts in accessible names.
    return " ".join("".join(
        character for character in value
        if unicodedata.category(character) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    ).split())


def _quoted_label(value: str) -> str:
    match = _LABEL.search(value)
    if not match:
        return ""
    try:
        decoded = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        decoded = match.group(1)
    return " ".join(str(decoded).split())


def filter_accessibility_snapshot(snapshot: str, *, max_chars: int = MAX_BROWSER_TEXT) -> dict:
    """Keep readable page labels/text; discard navigation, controls and tree metadata.

    The source is untrusted browser content. This function does not interpret
    its instructions or URLs and deliberately returns no raw snapshot artifact.
    """
    if not isinstance(snapshot, str):
        raise TypeError("browser snapshot must be text")
    if not isinstance(max_chars, int) or not 1 <= max_chars <= MAX_BROWSER_TEXT:
        raise ValueError("max_chars must be between 1 and 24000")

    lines: list[str] = []
    skipped_indent: int | None = None
    for line in snapshot.splitlines():
        match = _NODE.match(line)
        if not match:
            continue
        indent = len(match.group("indent"))
        if skipped_indent is not None:
            if indent > skipped_indent:
                continue
            skipped_indent = None

        role = match.group("role")
        rest = match.group("rest")
        if role in _SKIP_SUBTREES or "[aria-hidden]" in rest:
            # Playwright emits both `- navigation:` and `- button "X":`;
            # skip the subtree for either form, not only nodes ending in `:`.
            skipped_indent = indent
            continue
        if role not in _TEXT_ROLES or role.startswith("/"):
            continue

        value = ""
        if role in {"heading", "link", "generic"}:
            value = _quoted_label(rest)
        if not value and ":" in rest:
            value = rest.split(":", 1)[1].strip()
            if value.startswith("|") or value.startswith(">"):
                value = ""
            if value.startswith('"'):
                value = _quoted_label(value)
        value = _plain_text(value)
        if _SKIP_UI_LABEL.fullmatch(value):
            if rest.rstrip().endswith(":"):
                skipped_indent = indent
            continue
        # Playwright snapshots may include icon-font glyphs as text nodes.
        if not value or not any(character.isalnum() for character in value):
            continue
        if not lines or lines[-1] != value:
            lines.append(value)

    content = "\n".join(lines)
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars].rsplit("\n", 1)[0] or content[:max_chars]
    return {
        "content": content,
        "input_chars": len(snapshot),
        "filtered_chars": len(content),
        "truncated": truncated,
        "quality_status": "INCOMPLETE_TRUNCATED" if truncated else "UNASSESSED_REVIEW_REQUIRED",
        "fidelity_assessed": False,
        "untrusted": True,
    }
