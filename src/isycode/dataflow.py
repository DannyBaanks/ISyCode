"""Small, deterministic primitives for processing accessibility snapshots."""

from __future__ import annotations

import json
import math
import multiprocessing
import re
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    Executor,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass
from typing import Callable, Generic, Literal, Sequence, TypeVar


_NODE = re.compile(r"^(?P<indent>\s*)-\s+(?P<role>[a-z][a-z0-9_-]*)(?P<rest>.*)$")
_SKIP_SUBTREES = frozenset(
    {
        "banner", "navigation", "contentinfo", "dialog", "search", "form",
        "toolbar", "menu", "menuitem", "tablist", "tab", "button", "textbox",
        "combobox", "checkbox", "radio", "img", "image", "separator",
    }
)
_LABEL = re.compile(r'"((?:\\.|[^"\\])*)"')
_SKIP_UI_LABEL = re.compile(
    r"^(?:skip|jump) to (?:main )?(?:content|search)"
    r"|accessibility links"
    r"|keyboard shortcuts for audio player"
    r"|subscribe(?: to)?"
    r"|you must be signed in to .+"
    r"|(?:fork|star)(?: \([\d.,]+[kKmM]?\))?"
    r"|(?:repository )?navigation$",
    re.IGNORECASE,
)

T = TypeVar("T")
R = TypeVar("R")


class DataflowExecutionError(RuntimeError):
    """Bounded worker failure metadata; never includes the submitted item."""

    def __init__(self, index: int, reason: str, timed_out: bool):
        if reason not in {"timeout", "worker_exception"}:
            reason = "worker_exception"
        self.index = index
        self.reason = reason
        self.timed_out = timed_out
        super().__init__(f"dataflow chunk {index}: {reason}")


def _make_executor(executor: Literal["thread", "process"], workers: int) -> Executor:
    if executor == "thread":
        return ThreadPoolExecutor(max_workers=workers)
    # TUI and test runners may already have threads (logging, terminal UI,
    # provider clients). Forking those processes can deadlock; spawn starts a
    # clean worker interpreter with only the picklable task payload.
    return ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
    )


def _validate_pool(pool: Executor, executor: str, workers: int) -> None:
    expected_type = ThreadPoolExecutor if executor == "thread" else ProcessPoolExecutor
    if not isinstance(pool, expected_type):
        raise TypeError(f"pool must match the selected {executor} executor")
    if getattr(pool, "_max_workers", None) != workers:
        raise ValueError("workers must match the supplied pool size")


def map_ordered(
    items: Sequence[T],
    worker: Callable[[T], R],
    *,
    workers: int,
    executor: Literal["serial", "thread", "process"],
    timeout_s: float | None = None,
    pool: Executor | None = None,
) -> list[R]:
    """Map over a bounded number of items and return results in source order.

    At most ``workers`` futures are outstanding. A failed or late run raises a
    metadata-only error and cancels futures that have not started. A caller-owned
    pool stays open; an owned pool is closed here. A running thread task cannot
    be force-stopped, so its eventual result is discarded after a timeout.
    """
    if not isinstance(workers, int) or isinstance(workers, bool) or workers <= 0:
        raise ValueError("workers must be a positive integer")
    if executor not in {"serial", "thread", "process"}:
        raise ValueError("executor must be serial, thread, or process")
    if timeout_s is not None and (
        not isinstance(timeout_s, (int, float))
        or isinstance(timeout_s, bool)
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ValueError("timeout_s must be a finite positive number")
    if executor == "serial":
        if pool is not None:
            raise TypeError("serial execution does not accept a pool")
        deadline = time.monotonic() + timeout_s if timeout_s is not None else None
        output: list[R] = []
        for index, item in enumerate(items):
            if deadline is not None and time.monotonic() >= deadline:
                raise DataflowExecutionError(index, "timeout", True)
            try:
                value = worker(item)
            except Exception:
                raise DataflowExecutionError(index, "worker_exception", False) from None
            if deadline is not None and time.monotonic() > deadline:
                raise DataflowExecutionError(index, "timeout", True)
            output.append(value)
        return output

    owns_pool = pool is None
    active_pool = _make_executor(executor, workers) if pool is None else pool
    _validate_pool(active_pool, executor, workers)
    deadline = time.monotonic() + timeout_s if timeout_s is not None else None
    results: list[object] = [None] * len(items)
    pending: dict[object, int] = {}
    next_index = 0

    def submit_available() -> None:
        nonlocal next_index
        while next_index < len(items) and len(pending) < workers:
            try:
                future = active_pool.submit(worker, items[next_index])
            except Exception:
                raise DataflowExecutionError(next_index, "worker_exception", False) from None
            pending[future] = next_index
            next_index += 1

    failed = False
    try:
        submit_available()
        while pending:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                failed = True
                index = min(pending.values())
                raise DataflowExecutionError(index, "timeout", True)
            done, _not_done = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                failed = True
                index = min(pending.values())
                raise DataflowExecutionError(index, "timeout", True)
            for future in sorted(done, key=lambda item: pending[item]):
                index = pending.pop(future)
                try:
                    results[index] = future.result()
                except Exception:
                    failed = True
                    raise DataflowExecutionError(index, "worker_exception", False) from None
            submit_available()
        return list(results)  # type: ignore[return-value]
    except BaseException:
        failed = True
        for future in pending:
            future.cancel()
        raise
    finally:
        if owns_pool:
            active_pool.shutdown(wait=not failed, cancel_futures=failed)


def accessibility_node_starts_skipped_subtree(role: str, rest: str) -> bool:
    """Keep splitter skip context aligned with the accessibility text filter."""
    if role in _SKIP_SUBTREES or "[aria-hidden]" in rest:
        return True
    if not rest.rstrip().endswith(":"):
        return False
    match = _LABEL.search(rest)
    if match is None:
        return False
    try:
        label = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        label = match.group(1)
    return bool(_SKIP_UI_LABEL.fullmatch(" ".join(str(label).split())))


@dataclass(frozen=True)
class DataflowChunk:
    """A source-ordered snapshot segment and the tree state active at its start."""

    index: int
    text: str
    ancestor_indents: tuple[int, ...]
    ancestor_roles: tuple[str, ...]
    starts_inside_skipped_subtree: bool
    skipped_ancestor_indent: int | None = None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("index must be nonnegative")
        if len(self.ancestor_indents) != len(self.ancestor_roles):
            raise ValueError("ancestor indentation and role context must have matching lengths")


@dataclass(frozen=True)
class DataflowChunkResult(Generic[T]):
    """A chunk's successful value or bounded error, never both or neither."""

    index: int
    value: T | None
    error: str | None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("index must be nonnegative")
        if (self.value is None) == (self.error is None):
            raise ValueError("exactly one of value or error must be populated")


def _context(
    stack: list[tuple[int, str, bool]],
    skipped_indent: int | None,
) -> tuple[tuple[int, ...], tuple[str, ...], bool, int | None]:
    indents = tuple(indent for indent, _role, _skip in stack)
    roles = tuple(role for _indent, role, _skip in stack)
    return indents, roles, skipped_indent is not None, skipped_indent


def _prepare_tree(stack: list[tuple[int, str, bool]], line: str) -> re.Match[str] | None:
    match = _NODE.match(line)
    if match is None:
        return None
    indent = len(match.group("indent"))
    while stack and stack[-1][0] >= indent:
        stack.pop()
    return match


def split_accessibility_snapshot(snapshot: str, *, target_chars: int) -> list[DataflowChunk]:
    """Split at line boundaries while carrying active ancestor roles and depth.

    The original source is retained byte-for-character when chunks are joined.
    A single line longer than ``target_chars`` is emitted intact as an oversized
    chunk; lines are never silently sliced or discarded.
    """

    if target_chars <= 0:
        raise ValueError("target_chars must be greater than zero")
    if not snapshot:
        return []

    chunks: list[DataflowChunk] = []
    stack: list[tuple[int, str, bool]] = []
    skipped_indent: int | None = None
    pending: list[str] = []
    pending_chars = 0
    pending_context = _context(stack, skipped_indent)

    def emit() -> None:
        nonlocal pending, pending_chars
        if not pending:
            return
        indents, roles, inside_skipped, skipped_indent = pending_context
        chunks.append(
            DataflowChunk(
                index=len(chunks),
                text="".join(pending),
                ancestor_indents=indents,
                ancestor_roles=roles,
                starts_inside_skipped_subtree=inside_skipped,
                skipped_ancestor_indent=skipped_indent,
            )
        )
        pending = []
        pending_chars = 0

    for line in snapshot.splitlines(keepends=True):
        match = _prepare_tree(stack, line)
        indent = len(match.group("indent")) if match is not None else None
        if skipped_indent is not None and indent is not None and indent <= skipped_indent:
            # Mirror the legacy filter's single active skip-depth state, including
            # its behavior when nested skip roles appear in the same subtree.
            skipped_indent = None
        if pending and pending_chars + len(line) > target_chars:
            emit()
        if not pending:
            pending_context = _context(stack, skipped_indent)
        pending.append(line)
        pending_chars += len(line)
        if match is not None:
            role = match.group("role")
            rest = match.group("rest")
            skip = accessibility_node_starts_skipped_subtree(role, rest)
            stack.append((len(match.group("indent")), role, skip))
            if skipped_indent is None and skip:
                skipped_indent = indent
        if pending_chars >= target_chars:
            emit()

    emit()
    return chunks
