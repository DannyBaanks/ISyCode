"""Pure helpers for Codex-style local file links, sidebar document tabs, and conversation files.

No Textual widgets and no direct filesystem I/O live here: every actual file read
or listing still executes through LocalWorkspaceReadOwner + IsySentinel.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import unquote, urlsplit

from rich.cells import cell_len
from rich.text import Text

from isycode.tui_theme import MUTED, TEXT

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_FRAG_LOC_RE = re.compile(r"^L?(\d+)(?:(?:C|:)(\d+))?(?:-L?\d+(?:(?:C|:)\d+)?)?$", re.IGNORECASE)
_COLON_LOC_RE = re.compile(r"^(?P<path>.+?):(?P<line>\d+)(?::(?P<col>\d+))?$")
_EXT_RE = re.compile(r"\.[A-Za-z0-9_+-]{1,12}$")
_MD_LINK_CAPTURE_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+(?:\s+\"[^\"]*\")?)\)")
_FENCE_RE = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_BARE_FILE_EXTS = (
    r"py|pyi|md|markdown|mb|rs|ts|tsx|js|jsx|mjs|cjs|json|jsonl|toml|ya?ml|"
    r"tcss|css|scss|html?|xml|svg|sh|bash|zsh|zig|go|c|h|cc|cpp|hpp|cs|java|kt|sql|txt|cfg|ini|env"
)
_PLAIN_FILE_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_./:@-])"
    r"(?P<ref>"
    r"file://[^\s<>()\[\]\"']+"
    r"|(?:(?:\.\.?/|[~/]|[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_+-]{1,12}(?::\d+(?::\d+)?|#L\d+(?:C\d+)?(?:-L\d+(?:C\d+)?)?)?)"
    r"|(?:[A-Za-z0-9_.-]+\.[A-Za-z0-9_+-]{1,12}(?::\d+(?::\d+)?|#L\d+(?:C\d+)?(?:-L\d+(?:C\d+)?)?))"
    r"|(?:[A-Za-z0-9_.-]+\.(?:" + _BARE_FILE_EXTS + r")(?![A-Za-z0-9_.-]))"
    r")"
)

_KNOWN_EXTENSIONLESS = frozenset({
    "agents",
    "build",
    "changelog",
    "claude",
    "containerfile",
    "dockerfile",
    "gemfile",
    "justfile",
    "license",
    "makefile",
    "procfile",
    "rakefile",
    "readme",
    "vagrantfile",
    "workspace",
})


@dataclass(frozen=True)
class SourceLocation:
    """1-based line and column inside a local file."""

    line: int
    column: int = 1


@dataclass(frozen=True)
class FileLink:
    """Parsed local file target with optional source location."""

    path: str
    location: SourceLocation | None = None

    @property
    def name(self) -> str:
        return Path(self.path).name or self.path


@dataclass
class SidebarDocTab:
    """State for one open document tab inside the right sidebar."""

    tab_id: str
    path: str
    title: str
    relative: str
    content: str
    size_bytes: int
    receipt_id: str
    is_markdown: bool
    location: SourceLocation | None = None
    binary_error: str | None = None


def normalize_file_key(path: str) -> str:
    """Stable deduplication key without touching disk."""
    cleaned = path.strip()
    if not cleaned:
        return ""
    if _WINDOWS_DRIVE_RE.match(cleaned):
        return cleaned.replace("\\", "/").casefold()
    return os.path.normpath(cleaned)


def _parse_fragment_location(fragment: str) -> SourceLocation | None:
    if not fragment:
        return None
    match = _FRAG_LOC_RE.match(fragment.strip())
    if not match:
        return None
    line = int(match.group(1))
    col = int(match.group(2)) if match.group(2) else 1
    if line < 1:
        return None
    return SourceLocation(line=line, column=max(1, col))


def _looks_like_file_path(candidate: str) -> bool:
    """Reject bare prose tokens and directories; accept plausible local file paths."""
    if not candidate or candidate.endswith(("/", "\\")):
        return False
    if candidate in {".", ".."}:
        return False
    name = candidate.replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name in {".", ".."}:
        return False
    if name.casefold() in _KNOWN_EXTENSIONLESS:
        return True
    if _EXT_RE.search(name):
        # Avoid bare version numbers like "1.2" or "3.14" unless inside a directory path.
        if "/" not in candidate and "\\" not in candidate:
            stem, ext = name.rsplit(".", 1)
            if not stem or (stem.isdigit() and ext.isdigit()):
                return False
        return True
    # Relative or absolute multi-segment paths like ".github/workflows/ci" or "/etc/hosts"
    return "/" in candidate or "\\" in candidate


def _resolve_lexical(raw_path: str, root: Path | None) -> str:
    if _WINDOWS_DRIVE_RE.match(raw_path):
        return os.path.normpath(raw_path) if os.name == "nt" else raw_path
    if raw_path.startswith("/"):
        return os.path.normpath(raw_path)
    if root is not None:
        return os.path.normpath(os.path.join(str(root), raw_path))
    return os.path.normpath(raw_path)


def parse_local_file_link(href: str, *, root: Path | None = None) -> FileLink | None:
    """Parse ``file://`` or local relative/absolute file references with optional line/col.

    Returns ``None`` for web URLs, non-local file hosts, queries, control chars, or
    bare prose that does not look like a local file target.
    """
    if not isinstance(href, str):
        return None
    raw = href.strip()
    if not raw or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return None
    if raw.startswith(("<", "#")):
        return None
    if "?" in raw:
        return None

    location: SourceLocation | None = None

    if raw.lower().startswith("file://"):
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return None
        netloc = parsed.netloc or ""
        if len(netloc) == 2 and netloc[0].isalpha() and netloc[1] == ":":
            # Tolerate 2-slash Windows drive URIs like file://C:/repo/main.py
            path_part = netloc + unquote(parsed.path or "")
        else:
            host = (parsed.hostname or "").casefold()
            if host not in {"", "localhost"}:
                return None
            path_part = unquote(parsed.path or "")
            # Windows file:///C:/foo -> C:/foo
            if len(path_part) >= 3 and path_part[0] == "/" and path_part[2] == ":" and path_part[1].isalpha():
                path_part = path_part[1:]
        if not path_part or path_part.endswith(("/", "\\")):
            return None
        location = _parse_fragment_location(parsed.fragment)
        if location is None:
            colon = _COLON_LOC_RE.match(path_part)
            if colon and not _WINDOWS_DRIVE_RE.match(path_part[len(colon.group("path")):]):
                path_part = colon.group("path")
                line = int(colon.group("line"))
                col = int(colon.group("col")) if colon.group("col") else 1
                if line >= 1:
                    location = SourceLocation(line=line, column=max(1, col))
        if not _looks_like_file_path(path_part):
            return None
        return FileLink(path=_resolve_lexical(path_part, root), location=location)

    # Reject other URI schemes (http://, https://, mailto:, ssh://, data:, etc.)
    if _SCHEME_RE.match(raw):
        return None
    if raw.lower().startswith(("mailto:", "javascript:", "data:", "tel:")):
        return None

    # Split optional #fragment
    path_part = raw
    if "#" in path_part:
        path_part, frag = path_part.split("#", 1)
        location = _parse_fragment_location(frag)
        if frag and location is None:
            # Allow Markdown heading anchors on markdown files (e.g. GUIA.md#como-ejecutarlo)
            if not path_part.lower().endswith((".md", ".markdown", ".mdown", ".mkdn")):
                return None

    # Split optional :line[:col] suffix (preserve Windows drive letter C:\...)
    if location is None:
        colon = _COLON_LOC_RE.match(path_part)
        if colon:
            candidate = colon.group("path")
            if candidate and not (len(candidate) == 1 and candidate.isalpha()):
                line = int(colon.group("line"))
                col = int(colon.group("col")) if colon.group("col") else 1
                if line >= 1:
                    path_part = candidate
                    location = SourceLocation(line=line, column=max(1, col))

    path_part = unquote(path_part)
    if not _looks_like_file_path(path_part):
        return None
    return FileLink(path=_resolve_lexical(path_part, root), location=location)


def extract_file_links_from_markdown(text: str, *, root: Path | None = None) -> list[FileLink]:
    """Extract local file links from Markdown links and safe file references outside fences."""
    if not text:
        return []
    found: list[FileLink] = []
    seen: set[str] = set()

    def _add(link: FileLink | None) -> None:
        if link is None:
            return
        key = normalize_file_key(link.path)
        if not key or key in seen:
            return
        seen.add(key)
        found.append(link)

    pieces = _FENCE_RE.split(text)
    for index in range(0, len(pieces), 2):
        chunk = _INLINE_CODE_RE.sub(" ", pieces[index])
        def _capture_md(match: re.Match) -> str:
            dest = match.group(1).split()[0].strip()
            _add(parse_local_file_link(dest, root=root))
            return " "
        remainder = _MD_LINK_CAPTURE_RE.sub(_capture_md, chunk)
        for match in _PLAIN_FILE_REF_RE.finditer(remainder):
            raw = match.group("ref").rstrip(".,;:!?")
            _add(parse_local_file_link(raw, root=root))
    return found


def truncate_middle_path(path_text: str, max_cells: int, *, ellipsis: str = "...") -> str:
    """Truncate a directory path in the middle so prefix and tail folder remain legible."""
    if max_cells <= 0:
        return ""
    if cell_len(path_text) <= max_cells:
        return path_text
    ell_len = cell_len(ellipsis)
    if max_cells <= ell_len:
        return ellipsis[:max_cells]
    budget = max_cells - ell_len
    left_budget = max(1, (budget * 2) // 5)
    right_budget = max(1, budget - left_budget)

    left_chars: list[str] = []
    used = 0
    for ch in path_text:
        w = cell_len(ch)
        if used + w > left_budget:
            break
        left_chars.append(ch)
        used += w

    right_chars: list[str] = []
    used = 0
    for ch in reversed(path_text):
        w = cell_len(ch)
        if used + w > right_budget:
            break
        right_chars.append(ch)
        used += w
    right_chars.reverse()
    return "".join(left_chars) + ellipsis + "".join(right_chars)


def display_parent_dir(path: str, *, root: Path | None = None) -> str:
    """Return a clean parent directory label (relative to root when inside root)."""
    p = Path(path)
    parent = p.parent
    if root is not None:
        try:
            rel = parent.relative_to(root).as_posix()
            return "." if rel == "." else rel
        except ValueError:
            pass
    return parent.as_posix() if str(parent) not in {"", "."} else ""


def format_conversation_file_row(
    link: FileLink,
    *,
    root: Path | None = None,
    width: int = 38,
    ascii_only: bool = False,
) -> Text:
    """Format a 1-line Codex-style ``· filename  dir/.../tail`` row within ``width`` cells."""
    bullet = "- " if ascii_only else "· "
    name = link.name
    if link.location is not None:
        name = f"{name}:{link.location.line}"
    parent = display_parent_dir(link.path, root=root)
    if parent == ".":
        parent = ""

    row = Text()
    row.append(bullet, style=MUTED)
    avail = max(4, width - cell_len(bullet))
    name_cells = cell_len(name)
    if name_cells >= avail or not parent:
        shown_name = truncate_middle_path(name, avail, ellipsis="...") if name_cells > avail else name
        row.append(shown_name, style=TEXT)
        return row

    row.append(name, style=TEXT)
    remaining = avail - name_cells - 2
    if remaining >= 4:
        row.append("  ", style=MUTED)
        row.append(truncate_middle_path(parent, remaining, ellipsis="..."), style=MUTED)
    return row


class ConversationFileTracker:
    """Ordered, deduplicated list of files touched or referenced in the active conversation."""

    def __init__(self, *, max_entries: int = 200) -> None:
        self._max_entries = max(1, max_entries)
        self._entries: list[FileLink] = []

    @property
    def entries(self) -> tuple[FileLink, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def promote(self, links: Iterable[FileLink]) -> bool:
        """Promote links to the front (newest first), preserving prior location when omitted."""
        incoming = list(links)
        if not incoming:
            return False
        before = list(self._entries)
        by_key = {normalize_file_key(item.path): item for item in self._entries}
        ordered_new: list[FileLink] = []
        seen_new: set[str] = set()
        for link in incoming:
            key = normalize_file_key(link.path)
            if not key or key in seen_new:
                continue
            seen_new.add(key)
            existing = by_key.get(key)
            if existing is not None and link.location is None and existing.location is not None:
                link = replace(link, location=existing.location)
            ordered_new.append(link)
        if not ordered_new:
            return False
        kept = [item for item in self._entries if normalize_file_key(item.path) not in seen_new]
        self._entries = (ordered_new + kept)[:self._max_entries]
        return self._entries != before

    def record_path(
        self,
        path: str,
        *,
        root: Path | None = None,
        location: SourceLocation | None = None,
    ) -> bool:
        link = parse_local_file_link(path, root=root)
        if link is None:
            return False
        if location is not None:
            link = replace(link, location=location)
        return self.promote([link])

    def record_markdown(self, text: str, *, root: Path | None = None) -> bool:
        links = extract_file_links_from_markdown(text, root=root)
        if not links:
            return False
        # Reverse so the last-mentioned link in a reply sits right at the top, or keep reading order
        return self.promote(links)


class SidebarTabManager:
    """State machine for open document tabs in the right sidebar."""

    def __init__(self, *, max_tabs: int = 12) -> None:
        self._max_tabs = max(1, max_tabs)
        self._tabs: list[SidebarDocTab] = []
        self._active_id: str | None = None
        self._scroll_offset: int = 0
        self._next_seq: int = 1

    @property
    def tabs(self) -> tuple[SidebarDocTab, ...]:
        return tuple(self._tabs)

    @property
    def active_id(self) -> str | None:
        return self._active_id

    @property
    def active_tab(self) -> SidebarDocTab | None:
        if self._active_id is None:
            return None
        for tab in self._tabs:
            if tab.tab_id == self._active_id:
                return tab
        return None

    def clear(self) -> None:
        self._tabs.clear()
        self._active_id = None
        self._scroll_offset = 0

    def find_by_path(self, path: str) -> SidebarDocTab | None:
        key = normalize_file_key(path)
        for tab in self._tabs:
            if normalize_file_key(tab.path) == key:
                return tab
        return None

    def open_or_update(
        self,
        *,
        path: str,
        title: str,
        relative: str,
        content: str,
        size_bytes: int,
        receipt_id: str,
        is_markdown: bool,
        location: SourceLocation | None = None,
        binary_error: str | None = None,
    ) -> SidebarDocTab:
        existing = self.find_by_path(path)
        if existing is not None:
            existing.title = title
            existing.relative = relative
            existing.content = content
            existing.size_bytes = size_bytes
            existing.receipt_id = receipt_id
            existing.is_markdown = is_markdown
            existing.binary_error = binary_error
            if location is not None:
                existing.location = location
            self._active_id = existing.tab_id
            self._ensure_active_visible()
            return existing

        tab_id = f"doc-{self._next_seq}"
        self._next_seq += 1
        tab = SidebarDocTab(
            tab_id=tab_id,
            path=path,
            title=title,
            relative=relative,
            content=content,
            size_bytes=size_bytes,
            receipt_id=receipt_id,
            is_markdown=is_markdown,
            location=location,
            binary_error=binary_error,
        )
        if len(self._tabs) >= self._max_tabs:
            self._tabs.pop(0)
            self._scroll_offset = max(0, self._scroll_offset - 1)
        self._tabs.append(tab)
        self._active_id = tab.tab_id
        self._ensure_active_visible()
        return tab

    def activate(self, tab_id: str) -> SidebarDocTab | None:
        for tab in self._tabs:
            if tab.tab_id == tab_id:
                self._active_id = tab_id
                self._ensure_active_visible()
                return tab
        return None

    def close(self, tab_id: str) -> SidebarDocTab | None:
        index = next((i for i, tab in enumerate(self._tabs) if tab.tab_id == tab_id), None)
        if index is None:
            return self.active_tab
        self._tabs.pop(index)
        if not self._tabs:
            self._active_id = None
            self._scroll_offset = 0
            return None
        if self._active_id == tab_id:
            next_index = min(index, len(self._tabs) - 1)
            self._active_id = self._tabs[next_index].tab_id
        self._scroll_offset = min(self._scroll_offset, max(0, len(self._tabs) - 1))
        self._ensure_active_visible()
        return self.active_tab

    def scroll_left(self) -> None:
        self._scroll_offset = max(0, self._scroll_offset - 1)

    def scroll_right(self) -> None:
        if self._scroll_offset + 1 < len(self._tabs):
            self._scroll_offset += 1

    def _ensure_active_visible(self) -> None:
        if self._active_id is None:
            return
        idx = next((i for i, tab in enumerate(self._tabs) if tab.tab_id == self._active_id), None)
        if idx is None:
            return
        if idx < self._scroll_offset:
            self._scroll_offset = idx

    def visible_window(self, max_width: int) -> tuple[list[SidebarDocTab], bool, bool]:
        """Return tabs that fit inside ``max_width`` cells plus ``(can_left, can_right)``."""
        if not self._tabs:
            return [], False, False
        budget = max(12, max_width)
        start = min(self._scroll_offset, max(0, len(self._tabs) - 1))

        def _tab_cells(tab: SidebarDocTab) -> int:
            # label (capped at 18 cells) + space + "×" + padding/gap
            return min(18, max(4, cell_len(tab.title))) + 4

        def _slice_from(offset: int) -> list[SidebarDocTab]:
            shown: list[SidebarDocTab] = []
            used = 0
            for tab in self._tabs[offset:]:
                cost = _tab_cells(tab)
                if shown and used + cost > budget:
                    break
                shown.append(tab)
                used += cost
            return shown

        shown = _slice_from(start)
        active_idx = next((i for i, tab in enumerate(self._tabs) if tab.tab_id == self._active_id), None)
        if active_idx is not None:
            while start < active_idx and all(tab.tab_id != self._active_id for tab in shown):
                start += 1
                shown = _slice_from(start)
        self._scroll_offset = start
        can_left = start > 0
        can_right = start + len(shown) < len(self._tabs)
        return shown, can_left, can_right


__all__ = [
    "ConversationFileTracker",
    "FileLink",
    "SidebarDocTab",
    "SidebarTabManager",
    "SourceLocation",
    "display_parent_dir",
    "extract_file_links_from_markdown",
    "format_conversation_file_row",
    "normalize_file_key",
    "parse_local_file_link",
    "truncate_middle_path",
]
