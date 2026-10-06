#!/usr/bin/env python3
"""G0-03 flow probe: read/edit/diff through the real owner path in Classic.

Counts approval screens, measures their latency and the total flow, then
checks the deny path (edit without a fresh request-bound approval changes
nothing) and the action journal. Output: sanitized flow.json next to this
script. Mirrors tests/test_daily_tui.py's read/edit/diff scenario, with
timers added. Run from the repo root: python3 <this file>.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_daily_tui import configure  # noqa: E402


def main() -> int:
    from isycode.action_audit import ActionAuditJournal
    from isycode.tui import TUIApp, WriteApprovalScreen, CommandApprovalScreen
    from isycode.approvals import ActionApprovalStore
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.workspace_write import WorkspaceWriteOwner

    monkey = pytest.MonkeyPatch()
    report: dict = {"sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                          capture_output=True, text=True).stdout.strip()}

    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            root = configure(tmp, monkey)
            (root / "app.py").write_text("value = 1\n")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "app.py"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test",
                            "-c", "user.email=test@example.com", "commit", "-q", "-m", "baseline"],
                           check=True)
            seen = []
            actions = [("workspace_read", {"path": "app.py"}),
                       ("workspace_edit", {"path": "app.py", "old_text": "value = 1",
                                           "new_text": "value = 2"}),
                       ("git_diff", {"path": "app.py"})]

            async def complete(provider, messages, **kwargs):
                index = len(seen)
                seen.append([dict(m) for m in messages])
                if index < len(actions):
                    name, arguments = actions[index]
                    return {"text": "", "tool_calls": [
                        {"id": f"c{index}", "type": "function",
                         "function": {"name": name, "arguments": json.dumps(arguments)}}]}
                kwargs["on_chunk"]("content", "Changed value to 2 and reviewed the diff.")
                return {"text": "Changed value to 2 and reviewed the diff.", "tool_calls": []}

            monkey.setattr("isycode.tui.provider_complete", complete)

            app = TUIApp()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                approvals: list[dict] = []
                started = time.monotonic()
                task = asyncio.create_task(app._run_chat("Change value to 2 and show the diff."))
                approved_screens = set()
                try:
                    for _ in range(80):
                        await pilot.pause(0.05)
                        screen = app.screen
                        if isinstance(screen, (WriteApprovalScreen, CommandApprovalScreen)) \
                                and id(screen) not in approved_screens:
                            approved_screens.add(id(screen))
                            approvals.append({"kind": type(screen).__name__,
                                              "latency_s": round(time.monotonic() - started, 3)})
                            await pilot.press("tab", "enter")
                        if task.done():
                            break
                    await asyncio.wait_for(task, timeout=10)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                total_s = round(time.monotonic() - started, 3)
                report["flow"] = {
                    "approvals_shown": len(approvals),
                    "approval_screens": approvals,
                    "total_s": total_s,
                    "file_after": (root / "app.py").read_text().strip(),
                    "journal": ActionAuditJournal(root).verify().status,
                }

            deny_started = time.monotonic()
            owner = WorkspaceWriteOwner(root, WorkspaceAuthority(root), ActionApprovalStore())
            preview = owner.preview("app.py", "value = 3\n")
            denied = owner.apply(preview, None)
            report["deny"] = {"decision": denied.decision,
                              "reason": denied.reason,
                              "latency_s": round(time.monotonic() - deny_started, 3),
                              "file_after": (root / "app.py").read_text().strip()}

    asyncio.run(scenario())
    out = Path(__file__).with_name("flow.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
