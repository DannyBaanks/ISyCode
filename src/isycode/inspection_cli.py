"""Local, machine-readable inspection commands for ISyCode.

The module exposes metadata and existing session owners.  It performs no
provider or integration network calls.  Session mutations keep the same
Authority/Sentinel/receipt path as the TUI; destructive deletion additionally
requires an explicit ``--yes`` invocation and the pre-existing scoped grant.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO
import sys

from isycode.action_runtime import SessionDeleteOwner
from isycode.approvals import ActionApprovalStore
from isycode.config import discover_workspace_identity
from isycode.providers import model_slot, recent_models, selected_model_name, selected_provider_name
from isycode.security import ActionRequest
from isycode.session_owner import ChatSessionOwner
from isycode.usage import MAX_COUNTER, UsageLedger
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_setup import WorkspaceSetupStore, state_root


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_DENIED = 3


def _write(out: TextIO, value: object, *, json_output: bool = False) -> None:
    if json_output:
        out.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    elif isinstance(value, str):
        out.write(value.rstrip("\n") + "\n")
    else:
        out.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _session_owner(root: Path) -> ChatSessionOwner:
    authority = WorkspaceAuthority(root)
    sessions_root = WorkspaceSetupStore().sessions_root(root)
    return ChatSessionOwner(root, authority, sessions_root)


def _session_summary(session) -> dict:
    return {
        "id": session.session_id,
        "title": session.title,
        "messages": len(session.messages),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _session_detail(owner: ChatSessionOwner, session) -> dict:
    sanitized = json.loads(owner.store.serialize(session, sanitize=True))
    return {
        "id": sanitized["session_id"],
        "title": sanitized["title"],
        "messages": sanitized["messages"],
        "created_at": sanitized["created_at"],
        "updated_at": sanitized["updated_at"],
        "state": sanitized["state"],
    }


def _sessions(args: list[str], root: Path, out: TextIO, json_output: bool) -> int:
    if not args:
        _write(out, {"error": "sessions requires list, last, show, search, rename or delete"},
               json_output=json_output)
        return EXIT_USAGE
    owner = _session_owner(root)
    operation, rest = args[0], args[1:]
    if operation in {"list", "last"}:
        outcome, sessions = owner.list_conversations()
        if outcome.decision != "ALLOW":
            _write(out, {"decision": outcome.decision, "reason": outcome.reason},
                   json_output=json_output)
            return EXIT_DENIED
        if operation == "list":
            _write(out, {"sessions": [_session_summary(item) for item in sessions],
                         "receipt": outcome.receipt.receipt_id}, json_output=json_output)
        else:
            _write(out, {"session": _session_summary(sessions[0]) if sessions else None,
                         "receipt": outcome.receipt.receipt_id}, json_output=json_output)
        return EXIT_OK
    if operation == "search":
        query = " ".join(rest).strip()
        if not query:
            return EXIT_USAGE
        # The search implementation loads through the bounded local store.  A
        # session.resume list decision is required first so search never becomes
        # a second unaudited read path.
        outcome, _ = owner.list_conversations()
        if outcome.decision != "ALLOW":
            _write(out, {"decision": outcome.decision, "reason": outcome.reason},
                   json_output=json_output)
            return EXIT_DENIED
        matches = owner.store.search(query)
        _write(out, {"sessions": [_session_summary(item) for item in matches],
                     "receipt": outcome.receipt.receipt_id}, json_output=json_output)
        return EXIT_OK
    if operation == "show" and len(rest) == 1:
        outcome, session = owner.resume(rest[0])
        if session is None:
            _write(out, {"decision": outcome.decision, "reason": outcome.reason},
                   json_output=json_output)
            return EXIT_DENIED
        _write(out, {"session": _session_detail(owner, session),
                     "receipt": outcome.receipt.receipt_id}, json_output=json_output)
        return EXIT_OK
    if operation == "rename" and len(rest) >= 2:
        session_id, title = rest[0], " ".join(rest[1:]).strip()
        outcome, changed = owner.manage("rename", session_id, title)
        _write(out, {"decision": outcome.decision, "session_id": changed,
                     "reason": outcome.reason,
                     "receipt": outcome.receipt.receipt_id if outcome.receipt else None},
               json_output=json_output)
        return EXIT_OK if outcome.decision == "ALLOW" else EXIT_DENIED
    if operation == "delete" and rest:
        yes = "--yes" in rest
        values = [item for item in rest if item != "--yes"]
        if len(values) != 1:
            return EXIT_USAGE
        session_id = values[0]
        read, session = owner.resume(session_id)
        if session is None:
            _write(out, {"decision": read.decision, "reason": read.reason},
                   json_output=json_output)
            return EXIT_DENIED
        if not yes:
            _write(out, {"status": "confirmation_required", "session": _session_summary(session),
                         "hint": "repeat with --yes after reviewing the exact session id"},
                   json_output=json_output)
            return EXIT_DENIED
        authority = WorkspaceAuthority(root)
        approvals = ActionApprovalStore()
        request = ActionRequest("session.delete", root, session_id,
                                {"session_id": session_id, "title": session.title[:80]},
                                execution_owner="session_delete")
        approval = approvals.issue(request, ttl_seconds=30)
        result = SessionDeleteOwner(root, authority, owner.store, approvals).delete(
            session_id, session.title, approval)
        _write(out, {"decision": result.decision, "reason": result.reason,
                     "receipt": result.receipt.receipt_id if result.receipt else None},
               json_output=json_output)
        return EXIT_OK if result.decision == "ALLOW" else EXIT_DENIED
    return EXIT_USAGE


def _models(out: TextIO, json_output: bool) -> int:
    _write(out, {
        "active": {"provider": selected_provider_name(), "model": selected_model_name()},
        "recent": recent_models(),
        "slots": {"small": model_slot("small")},
        "network_tested": False,
    }, json_output=json_output)
    return EXIT_OK


def _stats(root: Path, out: TextIO, json_output: bool) -> int:
    owner = _session_owner(root)
    outcome, sessions = owner.list_conversations()
    if outcome.decision != "ALLOW":
        _write(out, {"decision": outcome.decision, "reason": outcome.reason},
               json_output=json_output)
        return EXIT_DENIED
    total = UsageLedger()
    # Aggregate already-recorded local counters without creating requests.
    total.requests = total.input_tokens = total.output_tokens = total.unknown_requests = 0
    for session in sessions:
        state = session.state.get("usage")
        if state is None:
            continue
        try:
            item = UsageLedger.from_state(state)
        except ValueError:
            total.unknown_requests = min(MAX_COUNTER, total.unknown_requests + 1)
            continue
        for field in ("requests", "input_tokens", "output_tokens", "unknown_requests"):
            setattr(total, field, min(MAX_COUNTER, getattr(total, field) + getattr(item, field)))
    _write(out, {"workspace": str(root), "sessions": len(sessions),
                 "usage": total.to_state(), "cost": {"status": "unknown"},
                 "receipt": outcome.receipt.receipt_id}, json_output=json_output)
    return EXIT_OK


def _dirs(root: Path, out: TextIO, json_output: bool) -> int:
    state = state_root().expanduser()
    sources = [
        {"precedence": 1, "kind": "user-defaults",
         "path": str(UserDefaultsStore().path), "exists": UserDefaultsStore().path.is_file()},
        {"precedence": 2, "kind": "workspace",
         "path": str(root / ".isycode" / "config.json"),
         "exists": (root / ".isycode" / "config.json").is_file()},
        {"precedence": 3, "kind": "process-overrides", "path": None,
         "exists": True},
    ]
    _write(out, {"workspace": str(root), "state": str(state),
                 "configuration": sources,
                 "rule": "higher precedence overrides lower precedence; values are not printed"},
           json_output=json_output)
    return EXIT_OK


def _completion(shell: str, out: TextIO) -> int:
    commands = "sessions models stats dirs doctor completion cli tui update actualizar"
    if shell == "bash":
        out.write(f"complete -W '{commands}' isycode\n")
    elif shell == "zsh":
        out.write(f"compctl -k '({commands})' isycode\n")
    elif shell == "fish":
        for command in commands.split():
            out.write(f"complete -c isycode -f -a {command}\n")
    else:
        return EXIT_USAGE
    return EXIT_OK


def main(arguments: list[str], *, cwd: Path | None = None,
         out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int:
    json_output = "--json" in arguments
    args = [item for item in arguments if item != "--json"]
    if not args:
        return EXIT_USAGE
    try:
        root = discover_workspace_identity(cwd or Path.cwd()).workspace_root.resolve(strict=True)
        if args[0] == "sessions":
            return _sessions(args[1:], root, out, json_output)
        if args == ["models"]:
            return _models(out, json_output)
        if args == ["stats"]:
            return _stats(root, out, json_output)
        if args == ["dirs"]:
            return _dirs(root, out, json_output)
        if len(args) == 2 and args[0] == "completion":
            return _completion(args[1], out)
    except (OSError, ValueError, TypeError) as exc:
        _write(err, {"error": type(exc).__name__, "message": str(exc)[:200]},
               json_output=json_output)
        return EXIT_FAILED
    return EXIT_USAGE


__all__ = ["EXIT_DENIED", "EXIT_FAILED", "EXIT_OK", "EXIT_USAGE", "main"]
