"""Temporary roots a test can hand to the product's private-state checks.

ISyCode refuses a private folder with a symlinked ancestor, and macOS reaches
its temp folder through /var, so a folder taken from tempfile by its given name
is refused there for a reason that has nothing to do with the behaviour under
test. These helpers hand over the same folder by its link-free name.
"""
from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def fresh_tree(prefix: str = "isycode-test-") -> Path:
    """A new temporary folder, named so the link checks accept it."""
    created = Path(tempfile.mkdtemp(prefix=prefix))
    return created.resolve()


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


@contextmanager
def temporary_tree(prefix: str = "isycode-test-") -> Iterator[Path]:
    path = fresh_tree(prefix)
    try:
        yield path
    finally:
        remove_tree(path)
