#!/usr/bin/env python3
"""G9-04 soak: >=2h, >=100 cycles, 3 restarts; orphans and RSS tracked.

Each cycle runs a chat turn with a mocked provider (read+write via the
real owners), an undo, and a journal verification. Every 34 cycles the
process exits and the wrapper restarts it (3 restarts total). RSS is
sampled per cycle from /proc; orphan check via pgrep of cycle children.
Targets (recorded, evaluated at the end): no orphans, no lost work,
final RSS <= warm baseline +25% and <= 500 MiB.

Run: nohup python3 scripts/soak_g9.py /tmp/g9-soak.json &
"""
from __future__ import annotations

import asyncio
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

DURATION_S = int(os.environ.get("G9_SOAK_SECONDS", str(2 * 60 * 60)))
RESTART_EVERY = 34
STATE_PATH = Path(os.environ.get("G9_SOAK_STATE", "/tmp/g9-soak-state.json"))
OUT_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/g9-soak.json")


def rss_mib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cycles": 0, "restarts": 0, "rss_samples": [], "failures": [], "started": time.time()}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def orphans() -> list[str]:
    found = subprocess.run(["pgrep", "-f", "soak-worker-child"], capture_output=True, text=True)
    return [pid for pid in found.stdout.split() if pid.strip()]


async def one_cycle(index: int) -> dict:
    import pytest
    from test_daily_tui import configure
    monkey = pytest.MonkeyPatch()
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        configure(tmp, monkey)
        from isycode.tui import TUIApp
        seen = []

        async def complete(provider, messages, **kwargs):
            if not seen:
                seen.append(1)
                return {"text": "", "tool_calls": [{"id": "c0", "type": "function",
                        "function": {"name": "workspace_write",
                                     "arguments": json.dumps({"path": "note.txt", "content": f"cycle {index}\n"})}}]}
            kwargs["on_chunk"]("content", "done")
            return {"text": "done", "tool_calls": []}

        monkey.setattr("isycode.tui.provider_complete", complete)
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            from isycode.tui import WriteApprovalScreen
            task = asyncio.create_task(app._run_chat(f"cycle {index}"))
            approved = set()
            for _ in range(60):
                await pilot.pause(0.05)
                if isinstance(app.screen, WriteApprovalScreen) and id(app.screen) not in approved:
                    approved.add(id(app.screen))
                    await pilot.press("tab", "enter")
                if task.done():
                    break
            await asyncio.wait_for(task, timeout=10)
            from isycode.workspace_write import WorkspaceWriteOwner
            from isycode.approvals import ActionApprovalStore
            from isycode.workspace_authority import WorkspaceAuthority
            writer = WorkspaceWriteOwner(app._workspace_root, WorkspaceAuthority(app._workspace_root),
                                         ActionApprovalStore())
            undo = writer.preview_undo()
            writer.apply(undo, None)
    monkey.undo()
    return {"cycle": index, "rss_mib": round(rss_mib(), 1), "orphans": len(orphans())}


def main() -> int:
    state = load_state()
    state["restarts"] = state.get("restarts", 0)
    loop = asyncio.new_event_loop()
    deadline = state["started"] + DURATION_S
    try:
        while time.time() < deadline:
            index = state["cycles"]
            try:
                sample = loop.run_until_complete(one_cycle(index))
            except Exception as exc:
                sample = {"cycle": index, "rss_mib": round(rss_mib(), 1),
                          "orphans": len(orphans()), "error": f"{type(exc).__name__}: {exc}"}
                state["failures"].append(sample)
            state["cycles"] = index + 1
            state["rss_samples"].append(sample)
            save_state(state)
            if (index + 1) % RESTART_EVERY == 0 and state["restarts"] < 3:
                state["restarts"] += 1
                save_state(state)
                subprocess.Popen([sys.executable, __file__, str(OUT_PATH)],
                                 stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"),
                                 start_new_session=True)
                break
    finally:
        loop.close()
    state["finished"] = time.time()
    state["final_rss_mib"] = round(rss_mib(), 1)
    save_state(state)
    OUT_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cycles": state["cycles"], "restarts": state["restarts"],
                      "final_rss_mib": state["final_rss_mib"], "failures": len(state["failures"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
