"""Real-provider canary for ADR 0008 (step recovery) and ADR 0009 (continuity capsule).

Runs the real TUIApp chat turn against a real provider through the real owners
(ProviderNetworkOwner, Workspace Authority, IsySentinel, journal). Nothing in
the provider path is mocked. Two things are deliberately arranged and labelled
as such in the evidence:

- scenario A sets a 16k-token window in the ISOLATED preferences so that the
  capsule engages without sending a huge request;
- scenario C cuts a REAL stream on the client side after real chunks arrived
  (a server-side cut cannot be provoked on demand).

The API key is read once, in-process, from the user's saved key and is never
printed or written. All ISyCode state goes to a temporary directory.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--key-workspace", required=True)
parser.add_argument("--model", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--scenario", action="append", required=True, choices=["A1", "A2", "B", "C"])
parser.add_argument("--window", type=int, default=0, help="real window in tokens, for B")
args = parser.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)

# ── 1. key, read once with the real state, kept in process memory only ──
from isycode.headless import _register_saved_key_reader  # noqa: E402
from isycode.providers import load_provider_key  # noqa: E402

_register_saved_key_reader(Path(args.key_workspace).resolve())
key = load_provider_key("nvidia")
if not key:
    sys.exit("no NVIDIA key available")
from isycode.credentials import set_saved_secret_reader  # noqa: E402
set_saved_secret_reader(None)

CODEWORD = "ZAFIRO-7319"


def isolate(name: str) -> Path:
    base = out / f"state-{name}"
    project = base / "project"
    project.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "ISYCODE_STATE_HOME": str(base / "state"), "XDG_STATE_HOME": str(base / "xdg"),
        "XDG_CONFIG_HOME": str(base / "config"), "ISYCODE_PROVIDER": "nvidia",
        "ISYCODE_MODEL": args.model, "NVIDIA_NIM_API_KEY": key,
    })
    os.chdir(project)
    from isycode.user_defaults import UserDefaultsStore
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.workspace_trust import WorkspaceTrust
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic")
    authority = WorkspaceAuthority(project)
    authority.set_mode("classic")
    WorkspaceTrust().decline(authority)
    return project


def conversation(turns: int, size: int) -> list[dict]:
    filler = ("The parser module tokenizes input, builds an AST and reports errors with "
              "line numbers. ") * (size // 90 + 1)
    history = []
    for index in range(turns):
        lead = (f"Remember this code word for later: {CODEWORD}. " if index == 0 else "")
        history.append({"role": "user", "content": f"request-{index}: {lead}" + filler[:size]})
        history.append({"role": "assistant", "content": f"answer-{index}: noted. " + filler[:size]})
    return history


def shown(app) -> str:
    from isycode.tui import plain_text
    from isycode.tui_widgets import ChatArea
    parts = []
    for widget in app.query_one(ChatArea).walk_children():
        try:
            parts.append(plain_text(widget))
        except Exception:
            pass
    return "\n".join(parts)


def summarize(messages) -> dict:
    data = json.dumps(messages, ensure_ascii=False)
    return {"messages": len(messages), "chars": len(data),
            "sha256": hashlib.sha256(data.encode()).hexdigest(),
            "has_capsule": any(str(m.get("content", "")).startswith("Continuity capsule")
                               for m in messages if m.get("role") == "system"),
            "has_request_0": any("request-0:" in str(m.get("content", ""))
                                 for m in messages if m.get("role") == "user"),
            "has_summary_notes": any(str(m.get("content", "")).startswith("Notes summarizing")
                                     for m in messages if m.get("role") == "system")}


async def run(name: str) -> dict:
    project = isolate(name)
    import isycode.tui as tui_module
    from isycode.providers import record_model_metadata, save_model_slot
    from isycode.chat_transport import provider_complete as real_complete
    from isycode.action_audit import ActionAuditJournal
    from isycode.streaming import StreamError

    calls: list[dict] = []
    question = "What was the code word I asked you to remember? Reply with the code word only."
    if name in {"A1", "A2"}:
        record_model_metadata("nvidia", args.model, {"context_length": 16_000})  # arranged window
        if name == "A1":                                  # small slot elsewhere: capsule only
            save_model_slot("small", "openai", "gpt-4o-mini")
        history = conversation(20, 1_500)
    elif name == "B":
        record_model_metadata("nvidia", args.model, {"context_length": 900_000_000})  # "fits"
        size = int(args.window * 4.6 / 40) if args.window else 20_000
        history = conversation(20, size)
    else:
        history = []
        question = "Write four short sentences about why tests matter."

    async def complete(provider, messages, **kwargs):
        entry = {"n": len(calls) + 1, "t": time.time(), "model": provider.model,
                 "kind": "summary" if str(messages[0].get("content", "")).startswith("Summarize")
                 else "chat", **summarize(messages)}
        calls.append(entry)
        if name == "C" and entry["kind"] == "chat" and entry["n"] == 1:
            seen = {"chunks": 0}
            outer = kwargs.get("on_chunk")

            def cutting(kind, chunk):
                if outer:
                    outer(kind, chunk)
                if kind == "content" and chunk:
                    seen["chunks"] += 1
                    if seen["chunks"] == 3:
                        entry["cut_after_real_chunks"] = 3
                        raise StreamError("provider closed a truncated chunked stream")
            kwargs["on_chunk"] = cutting
        try:
            result = await real_complete(provider, messages, **kwargs)
        except Exception as exc:  # recorded, then raised to the product path unchanged
            from isycode.provider_errors import classify_provider_error
            info = classify_provider_error(exc)
            entry.update(error=type(exc).__name__, error_kind=info["error_kind"],
                         http_status=info["http_status"], provider_code=info["provider_code"])
            raise
        entry.update(ok=True, answer=str(result.get("text", ""))[:200],
                     usage=result.get("usage"))
        return result

    tui_module.provider_complete = complete

    async def no_catalog(self):
        return None
    tui_module.TUIApp._refresh_openisy = no_catalog

    report = {"scenario": name, "model": args.model, "started": time.strftime("%FT%TZ", time.gmtime())}
    app = tui_module.TUIApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app._history = [dict(m) for m in history]
        try:
            await asyncio.wait_for(app._run_chat(question), 300)
            report["turn"] = "completed"
        except Exception as exc:
            report["turn"] = f"raised {type(exc).__name__}"
        await pilot.pause()
        transcript = shown(app)
        final = app._history[-1] if app._history else {}
        report.update(
            final_role=final.get("role"), final_answer=str(final.get("content", ""))[:400],
            codeword_in_answer=CODEWORD in str(final.get("content", "")),
            notes=[line.strip() for line in transcript.splitlines()
                   if any(mark in line for mark in ("Context capsule", "Compact", "recovered",
                                                    "Recovery stopped", "retrying"))][:10],
            history_len=len(app._history),
        )
    report["calls"] = calls
    report["journal"] = ActionAuditJournal(project).verify().status
    report["finished"] = time.strftime("%FT%TZ", time.gmtime())
    return report


async def main():
    for name in args.scenario:
        report = await run(name)
        path = out / f"canary-{name}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({k: report[k] for k in ("scenario", "turn", "codeword_in_answer", "notes", "journal")},
                         ensure_ascii=False), flush=True)
        for call in report["calls"]:
            print("  ", json.dumps({k: call.get(k) for k in ("n", "kind", "messages", "chars", "has_capsule",
                                                          "has_request_0", "has_summary_notes", "error_kind",
                                                          "http_status", "provider_code", "ok")}), flush=True)

asyncio.run(main())
