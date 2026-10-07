"""Small asyncio shims so ISyCode keeps its declared Python 3.10 support.

``Task.cancelling()`` exists only on Python 3.11+. ISyCode needs to tell "the
user cancelled this turn" apart from "an inner request was cancelled (for
example to steer)". On 3.11+ the native counter answers that; on 3.10 the TUI
records the cancellations it requests through ``note_cancel_requested``.
"""
from __future__ import annotations

import asyncio
import weakref

_requested: "weakref.WeakSet[asyncio.Task]" = weakref.WeakSet()


def note_cancel_requested(task: asyncio.Task) -> None:
    """Remember that the caller is about to cancel ``task`` itself (3.10 fallback)."""
    _requested.add(task)


def cancel_requested(task: asyncio.Task | None) -> bool:
    """Whether cancellation of ``task`` itself is pending or in progress."""
    if task is None:
        return False
    native = getattr(task, "cancelling", None)
    if native is not None:
        return native() > 0
    return task in _requested


__all__ = ["cancel_requested", "note_cancel_requested"]
