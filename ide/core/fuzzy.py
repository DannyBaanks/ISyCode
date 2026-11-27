"""Pure-Python 8-tier fuzzy matcher inspired by Orca's ``match-quality.ts``.

Scoring is an integer where higher is better and ``None`` means "no match".
Tiers are designed so that *any* match in a better tier outranks *any* match in
a worse tier, which keeps ordering stable and predictable for quick-open UIs.

Tiers (base score, 1000 apart, higher = better):

====  ==============================  ===========================================
Tier  Name                            Example (query → candidate)
====  ==============================  ===========================================
8     Exact                           ``main.py`` → ``main.py``
7     Case-insensitive exact          ``MAIN.PY`` → ``main.py``
6     Prefix                          ``main`` → ``main.py``
5     Word-boundary prefix            ``read`` → ``file_read.py``
4     Word-initial / camelCase        ``fm`` → ``FileManager``
3     Substring                       ``ain`` → ``main.py``
2     Subsequence (tight gap bonus)   ``mny`` → ``main.py``
1     Empty query (browse all)        ``""`` → ``main.py``
====  ==============================  ===========================================

Within a tier, shorter candidates, earlier matches and tighter subsequence
spans score higher so the most "obvious" file floats to the top.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass

TIER_EXACT = 8
TIER_CASE_INSENSITIVE_EXACT = 7
TIER_PREFIX = 6
TIER_WORD_BOUNDARY = 5
TIER_ACRONYM = 4
TIER_SUBSTRING = 3
TIER_SUBSEQUENCE = 2
TIER_EMPTY_QUERY = 1

_TIER_BASE = 1000
# 8 tiers × 1000 leaves head-room; keep each component well under the tier gap.
_MAX_LENGTH_BONUS = 400
_MAX_POSITION_BONUS = 200
_MAX_GAP_PENALTY = 150
_MAX_SPAN_BONUS = 100

_WORD_SEPARATORS = frozenset("/\\._-: ")


class FuzzyError(ValueError):
    pass


def normalize(text: str) -> str:
    """NFKD casefold with combining marks stripped, for accent-insensitive match."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def is_word_start(candidate: str, index: int) -> bool:
    """True when ``index`` begins a word: start, after a separator, or an upper→lower camel hump."""
    if index <= 0:
        return True
    prev, cur = candidate[index - 1], candidate[index]
    if prev in _WORD_SEPARATORS:
        return True
    # camelCase / PascalCase hump: lower-or-digit followed by upper, or upper after upper-lower run.
    return cur.isupper() and (prev.islower() or prev.isdigit() or (index >= 2 and candidate[index - 2].islower()))



def _word_starts(original: str, normalized: str) -> list[int]:
    """Word-start indices valid for ``normalized``.

    camelCase humps only exist in the original casing, so starts are computed on
    ``original`` and reused for ``normalized`` when the two have equal length
    (true for ASCII and most text); otherwise the normalized text is used alone.
    """
    if len(original) == len(normalized):
        return [i for i in range(len(normalized)) if is_word_start(original, i)]
    return [i for i in range(len(normalized)) if is_word_start(normalized, i)]


def _word_boundary_score(q: str, c: str, original: str | None = None) -> int | None:
    starts = _word_starts(original if original is not None else c, c)
    # Tier 5: contiguous prefix of a word
    for i in starts:
        if c.startswith(q, i):
            return TIER_WORD_BOUNDARY * _TIER_BASE + _length_bonus(len(c)) + _position_bonus(i)
    # Tier 4: word initials / camelCase acronym, left-to-right
    starts_by_char: dict[str, list[int]] = {}
    for i in starts:
        starts_by_char.setdefault(c[i], []).append(i)
    positions: list[int] = []
    cursor = 0
    for ch in q:
        options = starts_by_char.get(ch)
        nxt = next((i for i in options if i >= cursor), None) if options else None
        if nxt is None:
            positions = []
            break
        positions.append(nxt)
        cursor = nxt + 1
    if len(positions) == len(q) and len(positions) > 1:
        gap = positions[-1] - positions[0] - (len(positions) - 1)
        bonus = max(0, _length_bonus(len(c)) + _position_bonus(positions[0]) - min(gap, _MAX_GAP_PENALTY))
        return TIER_ACRONYM * _TIER_BASE + bonus
    return None

def _length_bonus(length: int) -> int:
    return max(0, _MAX_LENGTH_BONUS - min(length, _MAX_LENGTH_BONUS))


def _position_bonus(index: int) -> int:
    return max(0, _MAX_POSITION_BONUS - min(index, _MAX_POSITION_BONUS))


def _subsequence_spans(query: str, candidate: str) -> list[tuple[int, int]] | None:
    """Greedy forward + backward tighten (fzf-style): returns matched char indices or None."""
    forward: list[int] = []
    it = iter(range(len(candidate)))
    qi = 0
    for ci in it:
        if qi < len(query) and candidate[ci] == query[qi]:
            forward.append(ci)
            qi += 1
    if qi < len(query):
        return None
    # Walk backwards from the forward solution to pull matches as left as possible.
    backward: list[int] = []
    qi = len(query) - 1
    for ci in range(forward[-1], -1, -1):
        if qi >= 0 and candidate[ci] == query[qi]:
            backward.append(ci)
            qi -= 1
    backward.reverse()
    return [(i, i + 1) for i in backward]


def fuzzy_score(query: str, candidate: str) -> int | None:
    """Return an integer score for ``candidate`` against ``query`` or ``None`` if no match.

    Empty queries match everything with the lowest tier (so a cleared search box
    still lists items); non-string candidates are rejected.
    """
    if not isinstance(query, str) or not isinstance(candidate, str):
        raise FuzzyError("fuzzy_score expects two strings")
    if candidate == "":
        return None
    if query == "":
        return TIER_EMPTY_QUERY * _TIER_BASE
    q, c = normalize(query), normalize(candidate)
    if not q:
        return TIER_EMPTY_QUERY * _TIER_BASE
    if query == candidate:
        return TIER_EXACT * _TIER_BASE + _length_bonus(len(candidate))
    if q == c:
        return TIER_CASE_INSENSITIVE_EXACT * _TIER_BASE + _length_bonus(len(c))
    if c.startswith(q):
        return TIER_PREFIX * _TIER_BASE + _length_bonus(len(c)) + _position_bonus(0)
    # Tier 5 (word-boundary prefix) and Tier 4 (word-initial / camelCase acronym).
    word_score = _word_boundary_score(q, c, candidate)
    if word_score is not None:
        return word_score
    index = c.find(q)
    if index >= 0:
        return TIER_SUBSTRING * _TIER_BASE + _length_bonus(len(c)) + _position_bonus(index)
    spans = _subsequence_spans(q, c)
    if spans is None:
        return None
    span = spans[-1][1] - spans[0][0]
    extra = span - len(q)
    subseq_bonus = max(0, _length_bonus(len(c)) + _position_bonus(spans[0][0]) - min(extra * 4, _MAX_GAP_PENALTY))
    return TIER_SUBSEQUENCE * _TIER_BASE + subseq_bonus


def matched_ranges(query: str, candidate: str) -> list[tuple[int, int]]:
    """Character ranges of ``candidate`` (in its original casing) that the query matched.

    Used by UIs to bold the matched letters. Returns ``[]`` when there is no match.
    """
    if fuzzy_score(query, candidate) is None:
        return []
    if not query or not candidate:
        return []
    q = normalize(query)
    lowered = normalize(candidate)
    if len(lowered) != len(candidate):
        # Normalisation changed length (rare ligatures); fall back to whole-string highlight.
        return [(0, len(candidate))] if q.lower() in candidate.lower() else []
    index = lowered.find(q)
    if index >= 0:
        return [(index, index + len(q))]
    spans = _subsequence_spans(q, lowered)
    return spans or []


@dataclass(frozen=True)
class RankedItem:
    item: object
    score: int
    key: str


def rank_candidates(query: str, items: Iterable, key: Callable | None = None, *,
                   limit: int | None = None, reverse: bool = False) -> list:
    """Score and sort ``items`` by fuzzy match against ``query`` (best first).

    ``key`` extracts the comparable string from each item (default: identity).
    Items that do not match are dropped. Ties keep the original input order
    (stable sort). Returns the original items unless ``as_ranked=True``.
    """
    ranked = rank(query, items, key=key, limit=limit, reverse=reverse)
    return [r.item for r in ranked]


def rank(query: str, items: Iterable, key: Callable | None = None, *, limit: int | None = None,
         reverse: bool = False) -> list[RankedItem]:
    """Like :func:`rank_candidates` but returns :class:`RankedItem` with scores."""
    get = key or (lambda item: item)
    scored: list[tuple[int, int, RankedItem]] = []
    for order, item in enumerate(items):
        text = get(item)
        score = fuzzy_score(query, text) if isinstance(text, str) else None
        if score is None:
            continue
        scored.append((score, -order if not reverse else order, RankedItem(item, score, text)))
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [entry[2] for entry in scored][:limit] if limit is not None else [entry[2] for entry in scored]


__all__ = ["FuzzyError", "RankedItem", "fuzzy_score", "is_word_start", "matched_ranges", "normalize",
           "rank", "rank_candidates", "TIER_EXACT", "TIER_CASE_INSENSITIVE_EXACT", "TIER_PREFIX",
           "TIER_WORD_BOUNDARY", "TIER_ACRONYM", "TIER_SUBSTRING", "TIER_SUBSEQUENCE", "TIER_EMPTY_QUERY"]
