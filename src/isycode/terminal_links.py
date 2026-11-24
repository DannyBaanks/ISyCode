"""Hyperlinks and semantic colors for terminal-rendered chat and command text.

Links are explicit Rich ``link`` styles (OSC 8 on supporting terminals), never
browser launches during rendering. Selection/copy keeps the original text.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text

from isycode.tui_theme import CYAN, GREEN, MUTED, RED, YELLOW

_PR_RE = re.compile(r"\bPR\s+#?(\d{1,7})\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+")
_TOKEN_RE = re.compile(r"(?P<pr>\bPR\s+#?\d{1,7}\b)|(?P<url>https?://[^\s<>()\[\]\"']+)",
                       re.IGNORECASE)
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
        return f"[{raw}]({raw}){trailing}"

    segment = _URL_RE.sub(autolink, segment)
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


def rich_markdown(text: str, *, root: Path | str | None = None) -> RichMarkdown:
    """Markdown with autolinks and the repository's PR anchors."""
    repo_url = repository_web_url(root) if root is not None else None
    return RichMarkdown(linkify_markdown(text, repo_url), code_theme="monokai")


def _append_linked(result: Text, text: str, repo_url: str | None, style: str) -> None:
    cursor = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() and text[match.start() - 1] in "<](":
            continue
        raw = match.group(0)
        trailing = ""
        if match.group("url"):
            while raw and raw[-1] in ".,;:!?":
                trailing = raw[-1] + trailing
                raw = raw[:-1]
        result.append(text[cursor:match.start()], style=style)
        if match.group("pr") and repo_url:
            number = re.search(r"\d+", match.group("pr")).group(0)
            label, target = f"PR #{number}", f"{repo_url}/pull/{number}"
        elif match.group("url"):
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


__all__ = ["linkify_markdown", "repository_web_url", "rich_markdown", "semantic_plain"]
