"""One independent ISyCode instance for the session-continuity tests.

Run as its own process; it owns a ChatSessionOwner and answers one JSON command
per stdin line with one JSON line. Two of these are two real continuities.
With ISYCODE_TEST_SLOW_WRITE set, every transcript write sleeps inside the
locked section, widening the check→write window a race would need.
"""
import json
import os
import sys
import time
from pathlib import Path

from isycode.session_owner import ChatSessionOwner
from isycode.workspace_authority import WorkspaceAuthority

root, sessions = Path(sys.argv[1]), Path(sys.argv[2])
owner = ChatSessionOwner(root, WorkspaceAuthority(root), sessions)
if os.environ.get("ISYCODE_TEST_SLOW_WRITE"):
    delay = float(os.environ["ISYCODE_TEST_SLOW_WRITE"])
    original = owner.store._write

    def slow_write(session):
        time.sleep(delay)
        return original(session)

    owner.store._write = slow_write


def outcome(result):
    return {"decision": result.decision, "reason": result.reason}


for line in sys.stdin:
    command = json.loads(line)
    op = command["op"]
    sid = command.get("sid")
    if op == "resume":
        result, session = owner.resume(sid)
        reply = {**outcome(result), "messages": len(session.messages) if session else None}
    elif op == "record":
        if "wait_until" in command:  # start both writers at the same instant
            time.sleep(max(0.0, command["wait_until"] - time.time()))
        result, new_id = owner.record(sid, command["role"], command["content"],
                                      state=command.get("state"))
        reply = {**outcome(result), "sid": new_id}
    elif op == "manage":
        result, new_id = owner.manage(command["operation"], sid, command.get("data", ""))
        reply = {**outcome(result), "sid": new_id}
    elif op == "fork_mine":
        result, new_id = owner.save_continuity_as_new(sid, command["messages"],
                                                      command.get("state"), command["title"])
        reply = {**outcome(result), "sid": new_id}
    elif op == "reload":
        result, session = owner.reload_saved(sid)
        reply = {**outcome(result), "messages": [m["content"] for m in session.messages] if session else None,
                 "state": session.state if session else None}
    elif op == "keep_unsaved":
        owner.keep_unsaved(sid)
        reply = {"decision": "ALLOW", "reason": ""}
    elif op == "store_append":  # store-level read-modify-write, no owner base
        if "wait_until" in command:
            time.sleep(max(0.0, command["wait_until"] - time.time()))
        owner.store.append(sid, command["role"], command["content"])
        reply = {"decision": "ALLOW", "reason": ""}
    elif op == "status":
        reply = {"diverged": owner.is_diverged(sid), "base": owner.base_revision(sid)}
    else:
        reply = {"decision": "ERROR", "reason": f"unknown op {op}"}
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
