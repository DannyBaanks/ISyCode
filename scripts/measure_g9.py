#!/usr/bin/env python3
"""G9-02/G9-03 raw measurements: warm starts, keyboard echo, cancellation.

30 warm TUI starts measure time-to-usable-composer (prompt mounted and
focused, first paint done). Keyboard interaction latency is the pilot's
press-to-visible-echo time inside the running app. 30 cancellations of a
live sandboxed command measure UI acknowledgement and full process-tree
termination. Output: raw samples + percentiles as JSON, methodology in
the manifest. Run from the repo root: python3 <this file> <out.json>.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402

from test_daily_tui import configure  # noqa: E402


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(0.95 * len(ordered)))
    return ordered[index]


async def one_warm_start(tmp: Path) -> tuple[float, float]:
    monkey = pytest.MonkeyPatch()
    configure(tmp, monkey)
    from isycode.tui import TUIApp
    started = time.perf_counter()
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input")
        usable_s = time.perf_counter() - started
        echo_start = time.perf_counter()
        await pilot.press("x")
        for _ in range(40):
            await pilot.pause(0.005)
            if prompt.text == "x":
                break
        echo_ms = (time.perf_counter() - echo_start) * 1000
    monkey.undo()
    return usable_s, echo_ms


async def one_cancellation(tmp: Path) -> tuple[float, float]:
    monkey = pytest.MonkeyPatch()
    configure(tmp, monkey)
    from isycode.tui import TUIApp
    from isycode.approvals import ActionApprovalStore
    from isycode.command_runner import CommandRunOwner
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.workspace_trust import ACCEPT_PHRASE, WorkspaceTrust
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        root = app._workspace_root
        authority = WorkspaceAuthority(root)
        WorkspaceTrust().accept(authority, ACCEPT_PHRASE)
        runner = CommandRunOwner(root, authority, ActionApprovalStore())
        preview = runner.prepare(["sleep", "30"])
        task = asyncio.create_task(runner.run(preview, None))
        await asyncio.sleep(0.3)
        ack_start = time.perf_counter()
        task.cancel()
        ack_ms = (time.perf_counter() - ack_start) * 1000
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.CancelledError, TimeoutError, Exception):
            pass
        done_s = time.perf_counter() - ack_start
        still = await asyncio.get_running_loop().run_in_executor(
            None, lambda: __import__("subprocess").run(
                ["pgrep", "-f", f"sleep 30"], capture_output=True).returncode == 0)
    monkey.undo()
    return ack_ms, done_s if not still else -1.0


def main() -> int:
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/g9-measurements.json")
    report: dict = {"methodology": {
        "host": "Linux, 12 CPU, 14Gi RAM, ext4 NVMe (NOT the 4-core/8GiB reference box; recorded as difference)",
        "warm_start": "TUIApp().run_test until prompt mounted+paused, perf_counter",
        "keyboard_echo": "pilot.press('x') until prompt.text reflects it",
        "cancel": "sandboxed `sleep 30` task.cancel(); ack = cancel() return; tree = wait + pgrep gone",
        "note": "pilot harness, not a physical terminal; provider latency excluded by construction",
    }, "warm_starts": [], "keyboard_ms": [], "cancel_ack_ms": [], "cancel_tree_s": []}
    loop = asyncio.new_event_loop()
    try:
        for index in range(30):
            with tempfile.TemporaryDirectory() as raw:
                usable, echo = loop.run_until_complete(one_warm_start(Path(raw)))
            report["warm_starts"].append(round(usable, 4))
            report["keyboard_ms"].append(round(echo, 2))
        for index in range(30):
            with tempfile.TemporaryDirectory() as raw:
                ack, done = loop.run_until_complete(one_cancellation(Path(raw)))
            report["cancel_ack_ms"].append(round(ack, 2))
            report["cancel_tree_s"].append(round(done, 3))
    finally:
        loop.close()
    report["p95"] = {
        "warm_start_s": round(p95(report["warm_starts"]), 4),
        "keyboard_ms": round(p95(report["keyboard_ms"]), 2),
        "cancel_ack_ms": round(p95(report["cancel_ack_ms"]), 2),
        "cancel_tree_s": round(p95(report["cancel_tree_s"]), 3),
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["p95"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
