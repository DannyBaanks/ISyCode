"""Hyperlinks and semantic colors for terminal-rendered chat and command text.

Links are explicit Rich ``link`` styles (OSC 8 on supporting terminals), never
browser launches during rendering. Selection/copy keeps the original text.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text

from isycode.sidebar_files import FileLink, parse_local_file_link
from isycode.tui_theme import CYAN, GREEN, MUTED, RED, YELLOW

_PR_RE = re.compile(r"\bPR\s+#?(\d{1,7})\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+")
_BARE_FILE_EXTS = (
    r"py|pyi|md|markdown|mb|rs|ts|tsx|js|jsx|mjs|cjs|json|jsonl|toml|ya?ml|"
    r"tcss|css|scss|html?|xml|svg|sh|bash|zsh|zig|go|c|h|cc|cpp|hpp|cs|java|kt|sql|txt|cfg|ini|env"
)
_FILE_REF_BODY = (
    r"file://[^\s<>()\[\]\"']+"
    r"|(?:(?:\.\.?/|[~/]|[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_+-]{1,12}(?::\d+(?::\d+)?|#L\d+(?:C\d+)?(?:-L\d+(?:C\d+)?)?)?)"
    r"|(?:[A-Za-z0-9_.-]+\.[A-Za-z0-9_+-]{1,12}(?::\d+(?::\d+)?|#L\d+(?:C\d+)?(?:-L\d+(?:C\d+)?)?))"
    r"|(?:[A-Za-z0-9_.-]+\.(?:" + _BARE_FILE_EXTS + r")(?![A-Za-z0-9_.-]))"
)
_FILE_REF_RE = re.compile(r"(?<![A-Za-z0-9_./:@-])(?:" + _FILE_REF_BODY + r")")
_TOKEN_RE = re.compile(
    r"(?P<pr>\bPR\s+#?\d{1,7}\b)"
    r"|(?P<url>https?://[^\s<>()\[\]\"']+)"
    r"|(?P<file>(?<![A-Za-z0-9_./:@-])(?:" + _FILE_REF_BODY + r"))",
    re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_FENCE_RE = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)")
_INLINE_CODE_RE = re.compile(r"(`[^`\n]*`)")
_MAX_GIT_CONFIG_BYTES = 1024 * 1024


def _github_web_url(value: str) -> str | None:
    """Canonical public GitHub repository URL, with credentials discarded."""
    value = value.strip()
    if value.startswith("git@github.com:"):
        path = value.removeprefix("git@github.com:")
    elif value.startswith("ssh://git@github.com/"):
        path = value.removeprefix("ssh://git@github.com/")
    else:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if parsed.scheme not in {"http", "https"} or parsed.hostname != "github.com":
            return None
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git").strip("/")
    if path.count("/") != 1 or not all(path.split("/")):
        return None
    return f"https://github.com/{path}"


@lru_cache(maxsize=16)
def repository_web_url(root: Path | str) -> str | None:
    """Read origin without running Git or contacting the remote."""
    root = Path(root)
    dotgit = root / ".git"
    try:
        if dotgit.is_file():
            header = dotgit.read_text(encoding="utf-8").splitlines()[0]
            if not header.startswith("gitdir:"):
                return None
            git_dir = Path(header.split(":", 1)[1].strip())
            if not git_dir.is_absolute():
                git_dir = root / git_dir
        elif dotgit.is_dir():
            git_dir = dotgit
        else:
            return None
        config = git_dir / "config"
        if config.stat().st_size > _MAX_GIT_CONFIG_BYTES:
            return None
        lines = config.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, IndexError):
        return None
    in_origin = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped == '[remote "origin"]'
        elif in_origin and stripped.startswith("url") and "=" in stripped:
            return _github_web_url(stripped.split("=", 1)[1].strip())
    return None


def classify_link(href: str, *, root: Path | str | None = None) -> tuple[str, Any] | None:
    """Classify a rendered link href as ``('external', url)`` or ``('file', FileLink)``."""
    if not isinstance(href, str) or not href.strip():
        return None
    cleaned = href.strip()
    if cleaned.lower().startswith(("http://", "https://")):
        return ("external", cleaned)
    root_path = Path(root) if root is not None else None
    file_link = parse_local_file_link(cleaned, root=root_path)
    if file_link is not None:
        return ("file", file_link)
    return None


def _linkify_segment(segment: str, repo_url: str | None) -> str:
    protected: list[str] = []

    def protect(value: str) -> str:
        protected.append(value)
        return f"\x00{len(protected) - 1}\x00"

    segment = _MD_LINK_RE.sub(lambda match: protect(match.group(0)), segment)
    if repo_url:
        segment = _PR_RE.sub(
            lambda match: protect(f"[PR #{match.group(1)}]({repo_url}/pull/{match.group(1)})"),
            segment)

    def autolink(match: re.Match) -> str:
        if match.start() and segment[match.start() - 1] == "<":
            return match.group(0)
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,;:!?":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        return protect(f"[{raw}]({raw})") + trailing

    segment = _URL_RE.sub(autolink, segment)

    def autolink_file(match: re.Match) -> str:
        if match.start() and segment[match.start() - 1] in "<](":
            return match.group(0)
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,;:!?":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        if not raw or parse_local_file_link(raw) is None:
            return match.group(0)
        return protect(f"[{raw}]({raw})") + trailing

    segment = _FILE_REF_RE.sub(autolink_file, segment)
    for index, value in enumerate(protected):
        segment = segment.replace(f"\x00{index}\x00", value)
    return segment


def linkify_markdown(text: str, repo_url: str | None = None) -> str:
    """Autolink URLs and PR references, leaving code and existing links alone."""
    if not text:
        return text
    pieces = _FENCE_RE.split(text)
    for index in range(0, len(pieces), 2):
        inline = _INLINE_CODE_RE.split(pieces[index])
        for part in range(0, len(inline), 2):
            inline[part] = _linkify_segment(inline[part], repo_url)
        pieces[index] = "".join(inline)
    return "".join(pieces)


def _encode_markdown_file_links(text: str) -> str:
    """Escape local ``file://`` Markdown link destinations past markdown-it's BAD_PROTO_RE.

    ``markdown-it-py`` strips ``file:`` links as literal text. Rewriting validated
    local ``file://`` links to ``isyfile://`` lets the parser keep the link tokens,
    and ``selectable_markdown`` restores ``file://`` on the Rich ``Style``.
    """
    def _replace(match: re.Match) -> str:
        full = match.group(0)
        split = full.find("](")
        if split < 0:
            return full
        label = full[1:split]
        dest = full[split + 2:-1]
        if dest.lower().startswith("file://") and parse_local_file_link(dest) is not None:
            return f"[{label}](isyfile://{dest[7:]})"
        return full

    return _MD_LINK_RE.sub(_replace, text)


_BOX_CHAR_RE = re.compile(r"[\u2500-\u257f]")
_ASCII_BORDER_RE = re.compile(r"^\s*\+[-=+:]{3,}\+?\s*$")
_ASCII_SIDE_RE = re.compile(r"^\s*[|+].*[|+]\s*$")


def _art_line(line: str) -> int:
    """2 = drawn border (box-drawing run or ``+---+``), 1 = a side/inner row, 0 = prose."""
    if _ASCII_BORDER_RE.match(line) or len(_BOX_CHAR_RE.findall(line)) >= 2:
        return 2
    if _BOX_CHAR_RE.search(line) or _ASCII_SIDE_RE.match(line):
        return 1
    return 0


def fence_box_art(text: str) -> str:
    """Keep boxes the model drew in prose verbatim by fencing them as ``text``.

    Markdown strips leading spaces and reads ``*``/``_``/``|`` inside a drawn
    box, which breaks its columns. A run of at least two drawn lines, one of
    them a real border, becomes a fenced block; Markdown pipe tables have no
    drawn border, so they stay tables. Existing fences are left untouched.
    """
    pieces = _FENCE_RE.split(text)
    for index in range(0, len(pieces), 2):
        lines = pieces[index].split("\n")
        out = []
        cursor = 0
        while cursor < len(lines):
            if not _art_line(lines[cursor]) or lines[cursor].startswith("    "):
                out.append(lines[cursor])
                cursor += 1
                continue
            end = cursor
            while end < len(lines) and _art_line(lines[end]):
                end += 1
            run = lines[cursor:end]
            if len(run) >= 2 and any(_art_line(line) == 2 for line in run):
                out.extend(["```text", *run, "```"])
            else:
                out.extend(run)
            cursor = end
        pieces[index] = "\n".join(out)
    return "".join(pieces)


def rich_markdown(text: str, *, root: Path | str | None = None) -> RichMarkdown:
    """Markdown with autolinks and the repository's PR anchors."""
    repo_url = repository_web_url(root) if root is not None else None
    linked = _encode_markdown_file_links(linkify_markdown(fence_box_art(text), repo_url))
    return RichMarkdown(linked, code_theme="monokai")


def _append_linked(result: Text, text: str, repo_url: str | None, style: str) -> None:
    cursor = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() and text[match.start() - 1] in "<](":
            continue
        raw = match.group(0)
        trailing = ""
        if match.group("url") or match.group("file"):
            while raw and raw[-1] in ".,;:!?":
                trailing = raw[-1] + trailing
                raw = raw[:-1]
        result.append(text[cursor:match.start()], style=style)
        if match.group("pr") and repo_url:
            number = re.search(r"\d+", match.group("pr")).group(0)
            label, target = f"PR #{number}", f"{repo_url}/pull/{number}"
        elif match.group("url"):
            label = target = raw
        elif match.group("file") and parse_local_file_link(raw) is not None:
            label = target = raw
        else:
            result.append(raw, style=style)
            cursor = match.end()
            continue
        result.append(label, style=f"underline {CYAN} link {target}")
        result.append(trailing, style=style)
        cursor = match.end()
    result.append(text[cursor:], style=style)


def semantic_plain(text: str, *, root: Path | str | None = None) -> Text:
    """Plain output with links and conservative status colors, not a new parser."""
    repo_url = repository_web_url(root) if root is not None else None
    result = Text()
    for line in text.splitlines(keepends=True):
        lowered = line.lstrip().casefold()
        if lowered.startswith(("error", "failed", "failure", "exception", "traceback")):
            style = RED
        elif lowered.startswith(("warning", "warn", "denied", "timeout")):
            style = YELLOW
        elif lowered.startswith(("passed", "success", "allow", "done", "✓")):
            style = GREEN
        else:
            style = MUTED
        _append_linked(result, line, repo_url, style)
    return result


__all__ = [
    "FileLink",
    "classify_link",
    "linkify_markdown",
    "repository_web_url",
    "rich_markdown",
    "semantic_plain",
]
