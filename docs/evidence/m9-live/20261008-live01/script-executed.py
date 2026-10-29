#!/usr/bin/env python3
"""G9-06: one live everyday flow with an authorized provider, measured.

A real model, through the real TUI turn, owners, Authority, Sentinel,
approval screens and journal, is asked to fix a failing test in a small
fixture project: read the files, edit with workspace_edit, run the tests in
the real Bubblewrap sandbox with workspace_run, report. Each approval screen
is answered "y", as the person would. Recorded per provider request: wall
latency, time to first streamed chunk, tokens the provider reported, error
class. No cost is invented: the provider reports tokens, not prices.

The API key is read once from the saved key store, kept in memory, never
printed or written. All ISyCode state lives in a temporary directory.

Usage: python3 scripts/live_g9_06.py --key-workspace <dir> --model <id> --out <file.json>
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import subprocess
import platform
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--key-workspace", required=True)
parser.add_argument("--provider", default="nvidia")
parser.add_argument("--model", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()
output = Path(args.out).resolve()
if output.exists():
    raise SystemExit("output already exists; choose a new evidence path")
output.parent.mkdir(parents=True, exist_ok=True)

from isycode.headless import _register_saved_key_reader  # noqa: E402
from isycode.providers import PRESETS, load_provider_key  # noqa: E402

_register_saved_key_reader(Path(args.key_workspace).resolve())
key = load_provider_key(args.provider)
if not key:
    raise SystemExit(f"no saved key for {args.provider}")
from isycode.credentials import set_saved_secret_reader  # noqa: E402
set_saved_secret_reader(None)

base = Path(tempfile.mkdtemp(prefix="g9-06-"))
project = base / "project"
project.mkdir()
(project / "calc.py").write_text("def add(a, b):\n    return a - b\n")
(project / "test_calc.py").write_text(
    "import unittest\nfrom calc import add\n\n\nclass TestAdd(unittest.TestCase):\n"
    "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n\n"
    "if __name__ == '__main__':\n    unittest.main()\n")
os.environ.update({
    "ISYCODE_STATE_HOME": str(base / "state"), "XDG_STATE_HOME": str(base / "xdg"),
    "XDG_CONFIG_HOME": str(base / "config"), "ISYCODE_PROVIDER": args.provider,
    "ISYCODE_MODEL": args.model, PRESETS[args.provider].get("key_env") or "NVIDIA_NIM_API_KEY": key,
})
original_test_sha = hashlib.sha256((project / "test_calc.py").read_bytes()).hexdigest()
initial_test = subprocess.run([str(Path(sys.executable).resolve()), "-m", "unittest", "-v"], cwd=project, capture_output=True, text=True, timeout=30)
os.chdir(project)

from isycode.user_defaults import UserDefaultsStore  # noqa: E402
from isycode.workspace_authority import WorkspaceAuthority  # noqa: E402
from isycode.workspace_trust import WorkspaceTrust  # noqa: E402

UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic")
authority = WorkspaceAuthority(project)
authority.set_mode("classic")
WorkspaceTrust().decline(authority)          # untrusted folder: every change and command asks

import isycode.tui as tui_module  # noqa: E402
from isycode.action_audit import ActionAuditJournal  # noqa: E402
from isycode.chat_transport import provider_complete as real_complete  # noqa: E402
from isycode.tui_screens_approval import ApprovalScreen  # noqa: E402

PROMPT = ("The unit test in this project fails. Read calc.py and test_calc.py, fix the bug in "
          "calc.py with workspace_edit, then run `python3 -m unittest -v` with workspace_run "
          "and tell me the real result in one sentence.")
requests: list[dict] = []
screens: list[dict] = []


async def timed(provider, messages, **kwargs):
    entry = {"n": len(requests) + 1, "model": provider.model, "messages": len(messages),
             "request_chars": len(json.dumps(messages, ensure_ascii=False)), "started": time.time()}
    if len(requests) >= 8:
        raise RuntimeError("Live probe request budget reached")
    requests.append(entry)
    outer = kwargs.get("on_chunk")

    def first_chunk(kind, chunk):
        entry.setdefault("first_chunk_s", round(time.time() - entry["started"], 3))
        if outer:
            outer(kind, chunk)
    kwargs["on_chunk"] = first_chunk
    kwargs["max_tokens"] = 4096
    try:
        result = await real_complete(provider, messages, **kwargs)
    except Exception as exc:
        from isycode.provider_errors import classify_provider_error
        info = classify_provider_error(exc)
        entry.update(latency_s=round(time.time() - entry["started"], 3), error=info["error_kind"],
                     http_status=info["http_status"])
        raise
    entry.update(latency_s=round(time.time() - entry["started"], 3), usage=result.get("usage"),
                 tool_calls=[c.get("function", {}).get("name") for c in result.get("tool_calls") or []],
                 text_chars=len(result.get("text") or ""))
    return result

tui_module.provider_complete = timed


async def no_catalog(self):
    return None
tui_module.TUIApp._refresh_openisy = no_catalog
tui_module.TUIApp._check_gateway_async = no_catalog
tui_module.TUIApp._check_model = no_catalog


async def main() -> dict:
    report = {"provider": args.provider, "model": args.model,
              "started_utc": time.strftime("%FT%TZ", time.gmtime()),
              "environment": {"platform": platform.platform(), "python": platform.python_version(),
                              "bwrap": subprocess.run(["bwrap", "--version"], capture_output=True, text=True).stdout.strip()},
              "scope": "Real NVIDIA transport/model, owners, journal and bubblewrap; automated explicit approval of fixture edit/test commands through normal screens. Synthetic task, no real participants.",
              "initial_test": {"exit_code": initial_test.returncode, "stdout": initial_test.stdout, "stderr": initial_test.stderr},
              "fixture": str(project), "cost": {"status": "NOT_AVAILABLE", "reason": "Provider reports tokens, not billed currency; no price estimate invented."}}
    app = tui_module.TUIApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        started = time.time()
        turn = asyncio.create_task(app._run_chat(PROMPT))
        seen = set()
        while not turn.done() and time.time() - started < 600:
            await pilot.pause(0.1)
            if isinstance(app.screen, ApprovalScreen) and app.screen not in seen:
                seen.add(app.screen)
                screens.append({"screen": type(app.screen).__name__,
                                "t": round(time.time() - started, 3)})
                await pilot.press("y")
        try:
            await asyncio.wait_for(turn, 5)
            report["turn"] = "completed"
        except Exception as exc:
            report["turn"] = f"{type(exc).__name__}"
        report["turn_wall_s"] = round(time.time() - started, 3)
        final = app._history[-1] if app._history else {}
        report["final_answer"] = str(final.get("content", ""))[:600]
        report["tool_history"] = app._tool_history
    final_test = subprocess.run([str(Path(sys.executable).resolve()), "-m", "unittest", "-v"], cwd=project, capture_output=True, text=True, timeout=30)
    report["final_test"] = {"exit_code": final_test.returncode, "stdout": final_test.stdout, "stderr": final_test.stderr}
    report["tests_unchanged"] = original_test_sha == hashlib.sha256((project / "test_calc.py").read_bytes()).hexdigest()
    calc = (project / "calc.py").read_text()
    report.update(
        calc_py=calc, calc_fixed="a + b" in calc,
        requests=requests, approval_screens=screens,
        journal=ActionAuditJournal(project).verify().status,
        tokens_in=sum((r.get("usage") or {}).get("prompt_tokens", 0) or 0 for r in requests),
        tokens_out=sum((r.get("usage") or {}).get("completion_tokens", 0) or 0 for r in requests),
        errors=[r for r in requests if r.get("error")],
        finished_utc=time.strftime("%FT%TZ", time.gmtime()))
    journal = ActionAuditJournal(project)
    report["action_journal"] = journal.path.read_text() if journal.path.exists() else ""
    report["fixture_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in project.glob("*.py")}
    if any(not r.get("usage") for r in requests):
        report["token_usage_complete"] = False
    else:
        report["token_usage_complete"] = True
    from g9_live_checks import evaluate_live
    report["checks"] = evaluate_live(report)
    report["status"] = "PASS" if all(report["checks"].values()) else "FAIL"
    latencies = sorted(r["latency_s"] for r in requests if "latency_s" in r)
    report["latency_s"] = {"n": len(latencies), "min": latencies[0] if latencies else None,
                           "median": latencies[len(latencies) // 2] if latencies else None,
                           "max": latencies[-1] if latencies else None}
    return report

report = asyncio.run(main())
text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
if key in text:
    raise SystemExit("refusing to write a report that contains the API key")
with output.open("x", encoding="utf-8") as target:
    target.write(text)
print(json.dumps({k: report[k] for k in ("status", "turn", "calc_fixed", "journal", "tokens_in", "tokens_out",
                                          "latency_s", "turn_wall_s")}, ensure_ascii=False))
print("sha256", hashlib.sha256(text.encode()).hexdigest())

raise SystemExit(0 if report["status"] == "PASS" else 1)
