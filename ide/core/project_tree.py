"""Bounded project discovery shared by the model and the native file tree.

This is a filesystem view, not a sandbox or a command permission grant.
No file contents are included in directory snapshots.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

from core.file_icons import file_identity


EXCLUDED_DIRS = frozenset({".git", ".isyvm", ".isycode-ide", ".venv", "venv",
                         ".venv_linux", "node_modules", "__pycache__", ".pytest_cache",
                         ".mypy_cache", ".ruff_cache", ".cache", "build", "dist", "target"})
VISIBLE_DOTFILES = frozenset({".gitignore", ".gitattributes", ".editorconfig"})


def visible_name(name: str) -> bool:
    return name not in EXCLUDED_DIRS and (not name.startswith(".") or name in VISIBLE_DOTFILES)


class ProjectView:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, raw=".") -> Path:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("PATH_REQUIRED: use a relative project path")
        candidate = Path(raw)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("PATH_OUTSIDE_WORKSPACE: use a relative project path")
        if any(not visible_name(part) for part in candidate.parts):
            raise ValueError("PROJECT_PATH_EXCLUDED: path is excluded from the project view")
        path = self.root / candidate
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("PATH_OUTSIDE_WORKSPACE: project discovery does not follow symlinks")
        # An intermediate symlink must not become a traversal shortcut.
        current = self.root
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("PROJECT_SYMLINK_EXCLUDED: choose a real project directory")
        return path

    async def snapshot(self, raw=".", *, offset=0, limit=60) -> dict:
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
            raise ValueError("INVALID_PAGE: offset >= 0; limit between 1 and 100")
        directory = self.path(raw)
        if not directory.exists():
            raise ValueError("PROJECT_PATH_NOT_FOUND: directory does not exist in this project")
        if not directory.is_dir():
            raise ValueError("NOT_A_DIRECTORY: project_tree expands directories")
        entries, inspected, limited = [], 0, False
        started = time.monotonic()
        with os.scandir(directory) as scan:
            for entry in scan:
                inspected += 1
                if inspected % 64 == 0:
                    await asyncio.sleep(0)
                if inspected > 2_000 or time.monotonic() - started > 2:
                    limited = True
                    break
                if not visible_name(entry.name) or entry.is_symlink():
                    continue
                relative = Path(entry.path).relative_to(self.root).as_posix()
                is_dir = entry.is_dir(follow_symlinks=False)
                entries.append({"path": relative, "kind": "directory" if is_dir else "file",
                                "type": file_identity(relative, is_dir)[1]})
        entries.sort(key=lambda e: (e["kind"] != "directory", e["path"]))
        version = hashlib.sha256(json.dumps(entries, ensure_ascii=True).encode()).hexdigest()[:16]
        page, size = [], 0
        for item in entries[offset:offset + limit]:
            item_size = len(json.dumps(item, ensure_ascii=False))
            if size + item_size > 12_000:
                break
            page.append(item)
            size += item_size
        more = offset + len(page) < len(entries)
        return {"project": self.root.name, "path": directory.relative_to(self.root).as_posix(),
                "version": version, "entries": page, "next_offset": offset + len(page) if more else None,
                "truncated": limited or more, "scan_limited": limited,
                "scope": "one directory; relative paths; no file contents; excluded caches, hidden files and symlinks",
                "empty_visible_directory": not entries and not limited,
                "hint": ("This directory has no visible entries under the IDE filter. Do not retry broad discovery, invent paths or bypass exclusions. Explain the empty visible project and propose a plan from the user request; this does not prove hidden files are absent."
                         if not entries and not limited else
                         "Expand a directory with project_tree(path). Use next_offset for another page; refresh offset 0 if version changes.")}

    async def files(self, raw="."):
        """Yield visible files with cooperative cancellation and scan limits."""
        path = self.path(raw)
        if path.is_file():
            yield path
            return
        if not path.is_dir():
            raise ValueError("PATH_NOT_FOUND: project path does not exist")
        stack, visited, started = [path], 0, time.monotonic()
        while stack:
            directory = stack.pop()
            await asyncio.sleep(0)
            with os.scandir(directory) as scan:
                for entry in scan:
                    visited += 1
                    if visited % 64 == 0:
                        await asyncio.sleep(0)
                    if visited > 20_000 or time.monotonic() - started > 10:
                        raise ValueError("SEARCH_LIMIT: narrow the project path")
                    if not visible_name(entry.name) or entry.is_symlink():
                        continue
                    item = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(item)
                    elif entry.is_file(follow_symlinks=False):
                        yield item
