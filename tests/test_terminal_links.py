from pathlib import Path

from rich.console import Console
from rich.color import Color

from isycode.terminal_links import (
    linkify_markdown, repository_web_url, rich_markdown, semantic_plain,
)
from isycode.tui_copy import selectable_markdown
from isycode.operation_style import operation_color
from isycode.tui_theme import GREEN, RED, YELLOW


def repo(tmp_path: Path, url="git@github.com:DannyBaanks/ISyCode.git") -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(
        '[core]\n\trepositoryformatversion = 0\n'
        f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")
    repository_web_url.cache_clear()
    return root


def test_markdown_autolinks_prs_and_urls_without_nesting(tmp_path):
    root = repo(tmp_path)
    text = linkify_markdown(
        "Fix PR #117 and PR 118, plus https://example.com/x. "
        "Existing [PR #119](https://github.com/DannyBaanks/ISyCode/pull/119).",
        repository_web_url(root))
    assert "[PR #117](https://github.com/DannyBaanks/ISyCode/pull/117)" in text
    assert "[PR #118](https://github.com/DannyBaanks/ISyCode/pull/118)" in text
    assert "[https://example.com/x](https://example.com/x)." in text
    assert "[[PR #119]" not in text
    assert text.count("pull/119") == 1


def test_code_and_inline_code_are_not_linkified(tmp_path):
    root = repo(tmp_path)
    source = "`PR #117` and https://example.com\n```\nPR #118 https://example.org\n```"
    linked = linkify_markdown(source, repository_web_url(root))
    assert "`PR #117`" in linked
    assert "[https://example.com](https://example.com)" in linked
    assert "```\nPR #118 https://example.org\n```" in linked


def test_selectable_markdown_preserves_real_hyperlinks(tmp_path):
    root = repo(tmp_path)
    markdown = rich_markdown("Fix PR #117 and https://example.com/x", root=root)
    rendered = selectable_markdown(markdown)
    console = Console(record=True, width=120)
    segments = list(console.render(rendered))
    pr = next(segment for segment in segments if segment.text == "PR #117")
    url = next(segment for segment in segments if segment.text == "https://example.com/x")
    assert pr.style.link == "https://github.com/DannyBaanks/ISyCode/pull/117"
    assert url.style.link == "https://example.com/x"
    assert rendered.plain.rstrip("\n") == "Fix PR #117 and https://example.com/x"


def test_semantic_plain_colors_status_and_links(tmp_path):
    root = repo(tmp_path)
    text = semantic_plain("FAILED one test\nPR 117 passed\n", root=root)
    console = Console(record=True, width=120)
    segments = list(console.render(text))
    failed = next(segment for segment in segments if "FAILED" in segment.text)
    pr = next(segment for segment in segments if segment.text == "PR #117")
    assert failed.style.color == Color.parse(RED)
    assert pr.style.link == "https://github.com/DannyBaanks/ISyCode/pull/117"


def test_https_remote_credentials_are_never_exposed(tmp_path):
    root = repo(tmp_path, "https://user:secret@github.com/DannyBaanks/ISyCode.git")
    assert repository_web_url(root) == "https://github.com/DannyBaanks/ISyCode"


def test_operation_palette_is_semantic():
    assert operation_color("workspace_read") == operation_color("workspace_list")
    assert operation_color("workspace_run") == YELLOW
    assert operation_color("workspace_edit") == GREEN
    assert operation_color("workspace_delete") == RED
