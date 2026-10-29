"""Small, deterministic helpers for searching rendered console text."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextMatch:
    start: int
    end: int
    snippet: str


def find_text_matches(text: str, query: str, *, context: int = 52) -> list[TextMatch]:
    """Return case-insensitive occurrences and bounded snippets in source offsets."""
    needle = query.casefold()
    if not needle or not text:
        return []

    folded_parts: list[str] = []
    source_offsets: list[int] = []
    for source_offset, character in enumerate(text):
        folded_character = character.casefold()
        folded_parts.append(folded_character)
        source_offsets.extend([source_offset] * len(folded_character))
    folded = "".join(folded_parts)

    matches: list[TextMatch] = []
    cursor = 0
    while (found := folded.find(needle, cursor)) >= 0:
        end_folded = found + len(needle)
        start = source_offsets[found]
        end = source_offsets[end_folded - 1] + 1
        excerpt_start = max(0, start - max(0, context))
        excerpt_end = min(len(text), end + max(0, context))
        snippet = text[excerpt_start:excerpt_end]
        if excerpt_start:
            snippet = "…" + snippet
        if excerpt_end < len(text):
            snippet += "…"
        matches.append(TextMatch(start, end, snippet))
        cursor = found + max(1, len(needle))
    return matches
