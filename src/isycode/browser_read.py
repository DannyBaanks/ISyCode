"""Reduce Playwright accessibility snapshots to bounded, untrusted page text."""
from __future__ import annotations

import json
import re
import time
import unicodedata
from concurrent.futures import Executor
from typing import Literal

from .dataflow import (
    DataflowChunk,
    DataflowChunkResult,
    DataflowExecutionError,
    accessibility_node_starts_skipped_subtree,
    map_ordered,
    split_accessibility_snapshot,
)

MAX_BROWSER_TEXT = 24_000
_NODE = re.compile(r"^(?P<indent>\s*)-\s+(?P<role>[a-z][a-z0-9_-]*)(?P<rest>.*)$")
_LABEL = re.compile(r'"((?:\\.|[^"\\])*)"')
_SKIP_SUBTREES = frozenset({
    "banner", "navigation", "contentinfo", "dialog", "search", "form",
    "toolbar", "menu", "menuitem", "tablist", "tab", "button", "textbox",
    "combobox", "checkbox", "radio", "img", "image", "separator",
})
_TEXT_ROLES = frozenset({
    "heading", "paragraph", "text", "listitem", "link", "generic", "term",
    "definition", "blockquote", "code", "strong", "emphasis",
})
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


def _plain_text(value: str) -> str:
    # Private-use glyphs are common icon-font artifacts in accessible names.
    return " ".join("".join(
        character for character in value
        if unicodedata.category(character) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    ).split())


def _quoted_label(value: str) -> str:
    match = _LABEL.search(value)
    if not match:
        return ""
    try:
        decoded = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        decoded = match.group(1)
    return " ".join(str(decoded).split())


def _filter_snapshot_content(snapshot: str, *, initial_skipped_indent: int | None = None) -> str:
    lines: list[str] = []
    skipped_indent = initial_skipped_indent
    for line in snapshot.splitlines():
        match = _NODE.match(line)
        if not match:
            continue
        indent = len(match.group("indent"))
        if skipped_indent is not None:
            if indent > skipped_indent:
                continue
            skipped_indent = None

        role = match.group("role")
        rest = match.group("rest")
        if accessibility_node_starts_skipped_subtree(role, rest):
            # Playwright emits both `- navigation:` and `- button "X":`;
            # skip the subtree for either form, not only nodes ending in `:`.
            skipped_indent = indent
            continue
        if role not in _TEXT_ROLES or role.startswith("/"):
            continue

        value = ""
        if role in {"heading", "link", "generic"}:
            value = _quoted_label(rest)
        if not value and ":" in rest:
            value = rest.split(":", 1)[1].strip()
            if value.startswith("|") or value.startswith(">"):
                value = ""
            if value.startswith('"'):
                value = _quoted_label(value)
        value = _plain_text(value)
        if _SKIP_UI_LABEL.fullmatch(value):
            if rest.rstrip().endswith(":"):
                skipped_indent = indent
            continue
        # Playwright snapshots may include icon-font glyphs as text nodes.
        if not value or not any(character.isalnum() for character in value):
            continue
        if not lines or lines[-1] != value:
            lines.append(value)
    return "\n".join(lines)


def filter_accessibility_snapshot(snapshot: str, *, max_chars: int = MAX_BROWSER_TEXT) -> dict:
    """Keep readable page labels/text; discard navigation, controls and tree metadata.

    The source is untrusted browser content. This function does not interpret
    its instructions or URLs and deliberately returns no raw snapshot artifact.
    """
    if not isinstance(snapshot, str):
        raise TypeError("browser snapshot must be text")
    if not isinstance(max_chars, int) or not 1 <= max_chars <= MAX_BROWSER_TEXT:
        raise ValueError("max_chars must be between 1 and 24000")

    started = time.perf_counter()
    content = _filter_snapshot_content(snapshot)

    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars].rsplit("\n", 1)[0] or content[:max_chars]
    return {
        "content": content,
        "input_chars": len(snapshot),
        "filtered_chars": len(content),
        "processing_ms": (time.perf_counter() - started) * 1000,
        "truncated": truncated,
        "quality_status": "INCOMPLETE_TRUNCATED" if truncated else "UNASSESSED_REVIEW_REQUIRED",
        "fidelity_assessed": False,
        "untrusted": True,
    }


def filter_accessibility_chunk(chunk: DataflowChunk) -> DataflowChunkResult[str]:
    """Filter one immutable text chunk using its inherited skip-subtree state."""
    try:
        if not isinstance(chunk, DataflowChunk):
            raise TypeError("chunk must be a DataflowChunk")
        content = _filter_snapshot_content(
            chunk.text,
            initial_skipped_indent=(
                chunk.skipped_ancestor_indent
                if chunk.starts_inside_skipped_subtree
                else None
            ),
        )
        return DataflowChunkResult(index=chunk.index, value=content, error=None)
    except Exception as exc:
        index = chunk.index if isinstance(chunk, DataflowChunk) else 0
        return DataflowChunkResult(index=index, value=None, error=type(exc).__name__[:120])


def filter_accessibility_snapshot_chunked(
    snapshot: str,
    *,
    max_chars: int = MAX_BROWSER_TEXT,
    target_chunk_chars: int = 8_000,
    executor: Literal["serial", "thread", "process"] = "serial",
    workers: int = 1,
    timeout_s: float | None = None,
    pool: Executor | None = None,
) -> dict:
    """Filter structural chunks, then reassemble in validated source order.

    Any invalid or failed chunk invalidates the entire result. The global text
    cap is applied only after reassembly and is identical to the legacy path.
    The normal caller uses serial defaults; workers are an explicit experiment.
    """
    if not isinstance(snapshot, str):
        raise TypeError("browser snapshot must be text")
    if not isinstance(max_chars, int) or not 1 <= max_chars <= MAX_BROWSER_TEXT:
        raise ValueError("max_chars must be between 1 and 24000")

    started = time.perf_counter()
    chunks = split_accessibility_snapshot(snapshot, target_chars=target_chunk_chars)
    try:
        results = map_ordered(
            chunks,
            filter_accessibility_chunk,
            workers=workers,
            executor=executor,
            timeout_s=timeout_s,
            pool=pool,
        )
    except DataflowExecutionError as exc:
        return {
            "content": "",
            "input_chars": len(snapshot),
            "filtered_chars": 0,
            "processing_ms": (time.perf_counter() - started) * 1000,
            "truncated": False,
            "quality_status": "INCOMPLETE_DATAFLOW",
            "fidelity_assessed": False,
            "untrusted": True,
            "dataflow_error": f"chunk {exc.index} {exc.reason}",
        }
    if len(results) != len(chunks):
        failed_index = min(len(results), len(chunks) - 1) if chunks else 0
        failed_reason = f"chunk {failed_index} result missing"
        return {
            "content": "",
            "input_chars": len(snapshot),
            "filtered_chars": 0,
            "processing_ms": (time.perf_counter() - started) * 1000,
            "truncated": False,
            "quality_status": "INCOMPLETE_DATAFLOW",
            "fidelity_assessed": False,
            "untrusted": True,
            "dataflow_error": failed_reason,
        }

    output_lines: list[str] = []
    for expected_index, result in enumerate(results):
        if not isinstance(result, DataflowChunkResult) or result.index != expected_index:
            failure = f"chunk {expected_index} result invalid"
            return {
                "content": "",
                "input_chars": len(snapshot),
                "filtered_chars": 0,
                "processing_ms": (time.perf_counter() - started) * 1000,
                "truncated": False,
                "quality_status": "INCOMPLETE_DATAFLOW",
                "fidelity_assessed": False,
                "untrusted": True,
                "dataflow_error": failure,
            }
        if result.error is not None or result.value is None:
            return {
                "content": "",
                "input_chars": len(snapshot),
                "filtered_chars": 0,
                "processing_ms": (time.perf_counter() - started) * 1000,
                "truncated": False,
                "quality_status": "INCOMPLETE_DATAFLOW",
                "fidelity_assessed": False,
                "untrusted": True,
                "dataflow_error": f"chunk {expected_index} failed",
            }
        for line in result.value.split("\n") if result.value else ():
            if not output_lines or output_lines[-1] != line:
                output_lines.append(line)

    content = "\n".join(output_lines)
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars].rsplit("\n", 1)[0] or content[:max_chars]
    return {
        "content": content,
        "input_chars": len(snapshot),
        "filtered_chars": len(content),
        "processing_ms": (time.perf_counter() - started) * 1000,
        "truncated": truncated,
        "quality_status": "INCOMPLETE_TRUNCATED" if truncated else "UNASSESSED_REVIEW_REQUIRED",
        "fidelity_assessed": False,
        "untrusted": True,
    }
