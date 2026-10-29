#!/usr/bin/env python3
"""Measure offline TUI rendering cost for synthetic content/reasoning streams."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import textual
from rich.markdown import Markdown as RichMarkdown

from isycode.tui import TUIApp, ThoughtBlock
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_trust import WorkspaceTrust


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5,
                        help="samples for each mode and chunk size (default: 5)")
    parser.add_argument("--payload-chars", type=int, default=16_384,
                        help="characters per sample, maximum 65536 (default: 16384)")
    parser.add_argument("--chunk-chars", type=int, nargs="+", default=[16, 128],
                        help="stream chunk sizes (default: 16 128)")
    args = parser.parse_args(argv)
    if args.runs < 1 or not 1 <= args.payload_chars <= 65_536:
        parser.error("--runs must be positive and --payload-chars must be 1..65536")
    if not args.chunk_chars or any(size < 1 for size in args.chunk_chars):
        parser.error("--chunk-chars values must be positive")
    return args


def _median(records: list[dict], key: str) -> float:
    return statistics.median(record[key] for record in records)


async def _profile_case(mode: str, chunk_chars: int, runs: int, payload_chars: int,
                        counters: dict[str, float | int]) -> list[dict]:
    samples = []
    with tempfile.TemporaryDirectory(prefix="isycode-stream-profile-") as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        env = {
            "ISYCODE_STATE_HOME": str(root / "state"),
            "XDG_STATE_HOME": str(root / "xdg-state"),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "ISYCODE_PROVIDER": "openai",
            "ISYCODE_MODEL": "gpt-6-luna",
            "OPENAI_API_KEY": "profile-only-not-a-real-key",
        }

        async def no_external_catalog(self):
            return None

        async def complete(_provider, _messages, **kwargs):
            counters["provider_calls"] += 1
            remaining = payload_chars
            while remaining:
                size = min(chunk_chars, remaining)
                chunk = ("A" * size) if mode == "content" else ("thought " * ((size + 7) // 8))[:size]
                kwargs["on_chunk"]("content" if mode == "content" else "reasoning", chunk)
                counters["chunks"] += 1
                remaining -= size
            return {"text": "A" * payload_chars if mode == "content" else "",
                    "tool_calls": []}

        original_unmount = TUIApp.on_unmount

        async def test_unmount(self, event):
            await original_unmount(self, event)
            asyncio.get_running_loop().call_later(0.5, lambda: None)

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env))
            stack.enter_context(patch("isycode.providers.Provider.models",
                                      lambda provider: [provider.model]))
            stack.enter_context(patch.object(TUIApp, "_refresh_openisy", no_external_catalog))
            stack.enter_context(patch.object(TUIApp, "_check_gateway_async", no_external_catalog))
            stack.enter_context(patch.object(TUIApp, "_check_model", no_external_catalog))
            stack.enter_context(patch.object(TUIApp, "on_unmount", test_unmount))
            stack.enter_context(patch("isycode.tui.provider_complete", complete))
            previous_cwd = Path.cwd()
            os.chdir(project)
            try:
                UserDefaultsStore().update(new_workspace="temporary",
                                           new_workspace_mode="classic", locale="en")
                authority = WorkspaceAuthority(project)
                authority.set_mode("classic")
                WorkspaceTrust().decline(authority)
                app = TUIApp()
                async with app.run_test(size=(100, 30)) as pilot:
                    await pilot.pause()
                    for sample in range(runs):
                        before_counts = {key: counters[key] for key in counters}
                        wall_start = time.perf_counter()
                        cpu_start = time.process_time()
                        await app._run_chat(f"Synthetic {mode} sample {sample + 1}.")
                        await pilot.pause(0.02)
                        samples.append({
                            "wall_s": time.perf_counter() - wall_start,
                            "cpu_s": time.process_time() - cpu_start,
                            "markdown_cpu_s": counters["markdown_cpu_s"] - before_counts["markdown_cpu_s"],
                            "markdown_calls": counters["markdown_calls"] - before_counts["markdown_calls"],
                            "thought_cpu_s": counters["thought_cpu_s"] - before_counts["thought_cpu_s"],
                            "thought_calls": counters["thought_calls"] - before_counts["thought_calls"],
                            "provider_calls": counters["provider_calls"] - before_counts["provider_calls"],
                            "chunks": counters["chunks"] - before_counts["chunks"],
                        })
            finally:
                os.chdir(previous_cwd)
    return samples


async def _run(args: argparse.Namespace) -> dict:
    counters: dict[str, float | int] = {
        "markdown_cpu_s": 0.0, "markdown_calls": 0,
        "thought_cpu_s": 0.0, "thought_calls": 0,
        "provider_calls": 0, "chunks": 0,
    }

    def measured_markdown(*args, **kwargs):
        started = time.process_time()
        try:
            return RichMarkdown(*args, **kwargs)
        finally:
            counters["markdown_cpu_s"] += time.process_time() - started
            counters["markdown_calls"] += 1

    original_paint = ThoughtBlock._paint_preview

    def measured_paint(widget, *args, **kwargs):
        started = time.process_time()
        try:
            return original_paint(widget, *args, **kwargs)
        finally:
            counters["thought_cpu_s"] += time.process_time() - started
            counters["thought_calls"] += 1

    results = []
    with ExitStack() as stack:
        stack.enter_context(patch("isycode.tui_app_chat.RichMarkdown", measured_markdown))
        stack.enter_context(patch.object(ThoughtBlock, "_paint_preview", measured_paint))
        for chunk_chars in args.chunk_chars:
            for mode in ("content", "reasoning"):
                samples = await _profile_case(mode, chunk_chars, args.runs,
                                              args.payload_chars, counters)
                results.append({
                    "mode": mode,
                    "chunk_chars": chunk_chars,
                    "runs": len(samples),
                    "samples": samples,
                    "summary": {
                        "wall_s_median": _median(samples, "wall_s"),
                        "wall_s_min": min(sample["wall_s"] for sample in samples),
                        "wall_s_max": max(sample["wall_s"] for sample in samples),
                        "cpu_s_median": _median(samples, "cpu_s"),
                        "cpu_s_min": min(sample["cpu_s"] for sample in samples),
                        "cpu_s_max": max(sample["cpu_s"] for sample in samples),
                        "markdown_cpu_s_median": _median(samples, "markdown_cpu_s"),
                        "markdown_calls_median": _median(samples, "markdown_calls"),
                        "thought_cpu_s_median": _median(samples, "thought_cpu_s"),
                        "thought_calls_median": _median(samples, "thought_calls"),
                    },
                })
    return {
        "python": sys.version,
        "textual": textual.__version__,
        "platform": platform.platform(),
        "payload_chars": args.payload_chars,
        "runs_per_case": args.runs,
        "chunk_sizes": args.chunk_chars,
        "network": "disabled; synthetic provider only",
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    print(json.dumps(asyncio.run(_run(args)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
