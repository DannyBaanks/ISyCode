"""Real local MCP witness: the pinned context7 preset through the real TUI path.

Real: the npm download, the MCP server process, its stdio JSON-RPC handshake,
tools/list, tools/call (which reaches the context7 service), Workspace
Authority, IsySentinel, the approval screens and the journal. Simulated: only
the chat model, which is told to request the MCP tool, so no provider tokens
are spent and the MCP server is the thing under test. State is isolated.
"""
import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True)
parser.add_argument("--preset", default="context7")
args = parser.parse_args()
out = Path(args.out)
base = out / "state"
project = base / "project"
project.mkdir(parents=True, exist_ok=True)
os.environ.update({"ISYCODE_STATE_HOME": str(base / "state"), "XDG_STATE_HOME": str(base / "xdg"),
                   "XDG_CONFIG_HOME": str(base / "config"), "ISYCODE_PROVIDER": "openai",
                   "ISYCODE_MODEL": "simulated", "OPENAI_API_KEY": "simulated-not-sent"})
os.chdir(project)

from isycode.user_defaults import UserDefaultsStore  # noqa: E402
from isycode.workspace_authority import WorkspaceAuthority  # noqa: E402
from isycode.workspace_trust import WorkspaceTrust  # noqa: E402
UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic")
authority = WorkspaceAuthority(project)
authority.set_mode("classic")
WorkspaceTrust().decline(authority)

import isycode.tui as tui_module  # noqa: E402
from isycode.tui_screens_approval import ApprovalScreen  # noqa: E402
from isycode.action_audit import ActionAuditJournal  # noqa: E402

events: list[dict] = []
screens: list[dict] = []


def log(kind, **data):
    events.append({"t": round(time.time(), 3), "kind": kind, **data})
    print(json.dumps(events[-1], ensure_ascii=False)[:400], flush=True)


async def approve_screens(app, pilot, task, decisions):
    """Answer each approval screen in order with y/n until the task ends."""
    seen = set()
    while not task.done():
        await pilot.pause(0.1)
        screen = app.screen
        if isinstance(screen, ApprovalScreen) and id(screen) not in seen:
            seen.add(id(screen))
            key = decisions.pop(0) if decisions else "n"
            screens.append({"screen": type(screen).__name__, "key": key})
            log("screen", screen=type(screen).__name__, key=key)
            await pilot.press(key)
    return await task


async def main():
    calls = []
    plan: list = []

    async def complete(provider, messages, **kwargs):
        calls.append({"tools": [t["function"]["name"] for t in kwargs.get("tools") or []
                                if t["function"]["name"].startswith("mcp__")],
                      "tool_results": [m["content"] for m in messages if m.get("role") == "tool"]})
        if plan:
            return plan.pop(0)
        return {"text": "Done.", "tool_calls": []}

    tui_module.provider_complete = complete

    async def no_catalog(self):
        return None
    tui_module.TUIApp._refresh_openisy = no_catalog

    app = tui_module.TUIApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app._add_mcp_preset(args.preset)
        log("preset_added", preset=args.preset)

        # 1. Start: grant screen + exact start screen, both approved.
        started = time.time()
        task = asyncio.create_task(app._start_local_mcp(args.preset))
        await approve_screens(app, pilot, task, ["y", "y"])
        owner = app._local_mcp_owner()
        session = owner.sessions.get(args.preset)
        log("start_result", running=bool(session and session.process.returncode is None),
            seconds=round(time.time() - started, 1),
            tools=[t["name"] for t in (session.tools if session else [])])
        if not session:
            return
        functions = [t["function"]["name"] for t in owner.chat_tools()]
        resolve = next((f for f in functions if "resolve" in f), functions[0])
        docs = next((f for f in functions if "doc" in f and f != resolve), None)

        # 2. Rejected call: nothing may reach the server.
        plan[:] = [{"text": "", "tool_calls": [{"id": "m0", "type": "function", "function": {
            "name": resolve, "arguments": json.dumps({"libraryName": "textual",
                                                      "query": "textual widgets"})}}]}]
        task = asyncio.create_task(app._run_chat("Look up the Textual library (reject)"))
        await approve_screens(app, pilot, task, ["n"])
        rejected = json.loads(calls[-1]["tool_results"][-1])
        log("rejected_call", result=rejected)

        # 3. Approved call: the real server answers through the real owner.
        plan[:] = [{"text": "", "tool_calls": [{"id": "m1", "type": "function", "function": {
            "name": resolve, "arguments": json.dumps({"libraryName": "textual",
                                                      "query": "textual widgets"})}}]}]
        task = asyncio.create_task(app._run_chat("Look up the Textual library"))
        await approve_screens(app, pilot, task, ["y"])
        raw = calls[-1]["tool_results"][-1]
        result = json.loads(raw)
        log("approved_call", function=resolve, is_error=result.get("is_error"),
            text_chars=len(result.get("text", "")),
            text_sha256=hashlib.sha256(result.get("text", "").encode()).hexdigest(),
            text_head=result.get("text", "")[:300])

        # 4. Stop; a later call must not run.
        await owner.stop(args.preset)
        plan[:] = [{"text": "", "tool_calls": [{"id": "m2", "type": "function", "function": {
            "name": resolve, "arguments": json.dumps({"libraryName": "textual"})}}]}]
        task = asyncio.create_task(app._run_chat("Look it up again after stop"))
        await approve_screens(app, pilot, task, [])
        log("after_stop", result=calls[-1]["tool_results"][-1][:300],
            offered_tools=calls[-1]["tools"])

    report = ActionAuditJournal(project).verify(recent_limit=40)
    log("journal", status=report.status, decisions=report.decisions, receipts=report.receipts,
        mcp=[(r.get("kind"), r.get("action"), r.get("sentinel")) for r in report.recent
             if str(r.get("action", "")).startswith("mcp.")])
    (out / f"mcp-witness-{args.preset}.json").write_text(
        json.dumps({"preset": args.preset, "events": events, "screens": screens}, indent=2,
                   ensure_ascii=False) + "\n")

asyncio.run(main())
