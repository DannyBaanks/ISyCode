"""Console search finds every case-insensitive match with useful context."""
from isycode.search import find_text_matches


def test_search_finds_repeated_case_insensitive_matches():
    matches = find_text_matches("Fix Parser; then fix parser again", "FIX")

    assert [match.start for match in matches] == [0, 17]
    assert [match.end for match in matches] == [3, 20]


def test_search_context_is_bounded_around_each_match():
    text = "a" * 200 + "needle" + "b" * 200

    match, = find_text_matches(text, "needle", context=12)

    assert match.snippet == "…" + "a" * 12 + "needle" + "b" * 12 + "…"


def test_empty_or_missing_query_has_no_matches():
    assert find_text_matches("anything", "") == []
    assert find_text_matches("anything", "absent") == []
