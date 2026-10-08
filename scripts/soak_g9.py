#!/usr/bin/env python3
"""G9-04 soak: >=2h, >=100 cycles, 3 restarts; orphans and RSS tracked.

Each cycle runs a chat turn with a mocked provider (write via the
real owners), an undo, and a journal verification. Every 34 cycles the
process exits and the wrapper restarts it (3 restarts total). RSS is
sampled per cycle from /proc; surviving descendants are checked after unmount.
Warm baseline is current RSS after ten cycles in each worker.
Legacy state is rejected; shortened diagnostic runs cannot pass the 2h gate.
Targets (recorded, evaluated at the end): no orphans, no lost work,
final RSS <= warm baseline +25% and <= 500 MiB.

Run: python3 scripts/soak_g9.py /tmp/NEW-UNIQUE-soak.json
"""
from __future__ import annotations

import asyncio
import json
import os
import hashlib
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
OUT_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/g9-soak-v2.json").resolve()
STATE_PATH = Path(os.environ.get("G9_SOAK_STATE", str(OUT_PATH.with_suffix(".state.json")))).resolve()


def rss_mib() -> float:
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1024**2


def load_state() -> dict:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if state.get("format") != "g9-soak-v2":
            raise RuntimeError("legacy soak state cannot establish new checks; use a new output path")
        return state
    except FileNotFoundError:
        return {"format": "g9-soak-v2", "active_seconds": 0, "worker_cycles": 0, "warm_baselines": {}, "cycles": 0, "restarts": 0, "rss_samples": [], "failures": [], "started": time.time()}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def orphans() -> list[str]:
    # These are actual surviving descendants of this worker, not matches of a
    # never-used command-line marker. Read after the TUI cycle has unmounted.
    found, pending = [], [os.getpid()]
    while pending:
        pid = pending.pop()
        try:
            children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        except FileNotFoundError:
            continue
        found.extend(children)
        pending.extend(int(child) for child in children)
    return found


async def one_cycle(index: int) -> dict:
    import pytest
    monkey = pytest.MonkeyPatch()
    try:
        return await _cycle(index, monkey)
    finally:
        monkey.undo()


async def _cycle(index, monkey):
    from test_daily_tui import configure
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        root = configure(tmp, monkey)
        (root / "note.txt").write_text("original fixture\n")
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
                    await pilot.press("y")
                if task.done():
                    break
            await asyncio.wait_for(task, timeout=10)
            from isycode.workspace_write import WorkspaceWriteOwner
            from isycode.approvals import ActionApprovalStore
            from isycode.workspace_authority import WorkspaceAuthority
            writer = WorkspaceWriteOwner(app._workspace_root, WorkspaceAuthority(app._workspace_root),
                                         ActionApprovalStore())
            target = root / "note.txt"
            require(target.read_text() == f"cycle {index}\n", "write not verified")
            require(any(n["name"] == "workspace_write" for n in app._tool_history), "write result missing")
            undo = writer.preview_undo()
            # Simulated explicit user approval, still through the real owner/gates.
            result = writer.apply(undo, writer.approvals.issue(undo.request))
            require(result.decision == "ALLOW", f"undo not allowed: {result.decision}")
            require(result.receipt is not None, "undo receipt missing")
            require(target.read_text() == "original fixture\n", "undo not verified")
            from isycode.action_audit import ActionAuditJournal
            require(ActionAuditJournal(root).verify().status == "PASS", "journal verification failed")
    return {"cycle": index, "rss_mib": round(rss_mib(), 1), "orphans": len(orphans()), "write_verified": True, "undo_verified": True, "journal_verified": True}



def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def evaluate(state):
    samples = state["rss_samples"]
    baseline = state["warm_baselines"].get(str(state["restarts"]))
    return {
        "duration": state["finished"] - state["started"] >= 7200 and state.get("active_seconds", 0) >= 7200,
        "cycles": state["cycles"] >= 100,
        "restarts": state["restarts"] == 3,
        "no_failures": not state["failures"],
        "no_orphans": bool(samples) and all(s.get("orphans") == 0 for s in samples),
        "effects": bool(samples) and all(all(s.get(k) is True for k in
                    ("write_verified", "undo_verified", "journal_verified")) for s in samples),
        "rss": baseline is not None and state["final_rss_mib"] <= min(500, baseline * 1.25),
    }


def main() -> int:
    if STATE_PATH.exists() and "--resume-worker" not in sys.argv:
        raise RuntimeError("existing output state: use a new unique run path")
    state = load_state()
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if state.get("source_sha256", source_hash) != source_hash:
        raise RuntimeError("soak source changed; start a fresh run")
    state["source_sha256"] = source_hash
    state["restarts"] = state.get("restarts", 0)
    loop = asyncio.new_event_loop()
    worker_started = time.monotonic()
    deadline = worker_started + max(0, DURATION_S - state["active_seconds"])
    try:
        while time.monotonic() < deadline:
            index = state["cycles"]
            try:
                sample = loop.run_until_complete(one_cycle(index))
            except Exception as exc:
                sample = {"cycle": index, "rss_mib": round(rss_mib(), 1),
                          "orphans": len(orphans()), "error": f"{type(exc).__name__}: {exc}"}
                state["failures"].append(sample)
            state["worker_cycles"] += 1
            worker = str(state["restarts"])
            if state["worker_cycles"] == 10:
                state["warm_baselines"][worker] = sample["rss_mib"]
            sample["worker"] = worker
            state["cycles"] = index + 1
            state["rss_samples"].append(sample)
            save_state(state)
            if (index + 1) % RESTART_EVERY == 0 and state["restarts"] < 3:
                state["restarts"] += 1
                state["worker_cycles"] = 0
                state["active_seconds"] += time.monotonic() - worker_started
                save_state(state)
                subprocess.Popen([sys.executable, __file__, str(OUT_PATH), "--resume-worker"],
                                 stdout=open(str(OUT_PATH) + ".workers.log", "a"),
                                 stderr=subprocess.STDOUT,
                                 start_new_session=True, cwd=ROOT)
                return 0
    finally:
        loop.close()
    state["active_seconds"] += time.monotonic() - worker_started
    state["finished"] = time.time()
    state["final_rss_mib"] = round(rss_mib(), 1)
    state["checks"] = evaluate(state)
    state["status"] = "PASS" if all(state["checks"].values()) else "FAIL"
    save_state(state)
    OUT_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cycles": state["cycles"], "restarts": state["restarts"],
                      "final_rss_mib": state["final_rss_mib"], "failures": len(state["failures"])}))
    return 0 if state["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
