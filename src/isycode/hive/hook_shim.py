"""Hook shim — Python equivalent of cth-hook.cjs.

Receives hook events from agent CLIs via stdin (JSON) and forwards them to
the hive's Unix domain socket (HIVE_SOCK). Runs as a subprocess from the
agent's hook settings.

Protocol: line-delimited JSON over the socket.
  {"type": "pre_tool_use", "agent_id": "...", "tool_name": "...", "tool_input": {...}, "cwd": "..."}
  {"type": "post_tool_use", "agent_id": "...", "tool_name": "...", "tool_input": {...}}
  {"type": "stop", "agent_id": "...", "session_id": "..."}

Also implements the write guard check for PreToolUse.
"""
from __future__ import annotations

import os
import sys

# When executed directly (`python hook_shim.py`), Python puts the script's directory
# (`.../src/isycode/hive`) as sys.path[0]. Because `hive/types.py` exists, standard
# library modules (such as json, re, enum, pathlib) attempting `from types import ...`
# would erroneously load `hive/types.py` instead of the stdlib `types`, causing
# an ImportError.
# We must prune the script directory from sys.path and add `src/` before importing anything else.
_script_dir = os.path.dirname(os.path.abspath(__file__))
while sys.path and (
    os.path.abspath(sys.path[0]) == _script_dir
    or sys.path[0].replace("\\", "/").rstrip("/").endswith("/isycode/hive")
):
    sys.path.pop(0)

_src_dir = os.path.abspath(os.path.join(_script_dir, "..", ".."))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import json
import socket
import time
from pathlib import Path
from typing import Any

from isycode.hive.manager import HiveManager, HiveConfig
from isycode.hive.guard import hive_write_decision, HiveWriteInput


def get_hive_root() -> Path | None:
    """Resolve hive root from env or cwd."""
    # HIVE_ROOT is injected at spawn
    if hive_root := os.environ.get("HIVE_ROOT"):
        return Path(hive_root)
    # Fallback: walk up from cwd looking for hive/
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        if (p / "hive" / "registry.json").exists():
            return p / "hive"
    return None


def connect_sock(sock_path: str) -> socket.socket | None:
    """Connect to the hive socket."""
    try:
        if os.name == "nt":
            # Windows named pipe via socket (requires pywin32 for true named pipes)
            # For now, use a file-based fallback or loopback
            return None
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.25)
        sock.connect(sock_path)
        return sock
    except Exception:
        return None


def send_to_hive(sock_path: str, payload: dict[str, Any]) -> bool:
    """Send a payload to the hive socket. Fire-and-forget."""
    sock = connect_sock(sock_path)
    if not sock:
        return False
    try:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        sock.sendall(data)
        return True
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def handle_pre_tool_use(data: dict[str, Any], hive_root: Path, agent_id: str) -> dict[str, Any]:
    """Handle PreToolUse hook: check write guard, forward to hive."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    cwd = data.get("cwd", os.getcwd())

    # Read existing coordination state only. A hook cannot bootstrap or grant it.
    try:
        from isycode.hive.types import Registry, validate_identifier
        validate_identifier(agent_id)
        registry = Registry.from_dict(json.loads((hive_root / "registry.json").read_text(encoding="utf-8")))
        agent = registry.agents[agent_id]
        if agent.archived:
            raise ValueError("Archived Hive agent")
        decision = hive_write_decision({
            "tool": tool_name, "toolInput": tool_input, "cwd": cwd,
            "agentId": agent_id, "isGod": agent.is_god,
            "hiveRoot": str(hive_root), "caseInsensitive": os.name == "nt",
        })
    except (OSError, ValueError, TypeError, KeyError):
        decision = {"deny": True, "reason": "Hive identity or registry is unavailable."}
    if decision["deny"]:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                "permissionDecision": "deny", "permissionDecisionReason": decision["reason"]}}
    # Forward to hive for live status
    sock_path = os.environ.get("HIVE_SOCK")
    if sock_path:
        send_to_hive(sock_path, {
            "type": "pre_tool_use",
            "agent_id": agent_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": cwd,
            "ts": time.time(),
        })
    return {}


def handle_post_tool_use(data: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """Handle PostToolUse hook: forward to hive."""
    sock_path = os.environ.get("HIVE_SOCK")
    if sock_path:
        send_to_hive(sock_path, {
            "type": "post_tool_use",
            "agent_id": agent_id,
            "tool_name": data.get("tool_name", ""),
            "tool_input": data.get("tool_input", {}),
            "ts": time.time(),
        })
    return {"decision": "allow"}


def handle_stop(data: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """Handle Stop hook: forward to hive (triggers inbox drain)."""
    sock_path = os.environ.get("HIVE_SOCK")
    if sock_path:
        send_to_hive(sock_path, {
            "type": "stop",
            "agent_id": agent_id,
            "session_id": data.get("session_id", ""),
            "ts": time.time(),
        })
    return {"decision": "allow"}


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: isyco-hook <pre-tool-use|post-tool-use|stop>", file=sys.stderr)
        return 1

    hook_type = sys.argv[1]
    hive_root = get_hive_root()
    if not hive_root:
        print("HIVE_ROOT not set and hive not found", file=sys.stderr)
        return 1

    agent_id = os.environ.get("AGENT_ID", "unknown")

    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        print(f"Failed to parse stdin: {e}", file=sys.stderr)
        return 1

    if hook_type == "pre-tool-use":
        result = handle_pre_tool_use(payload, hive_root, agent_id)
    elif hook_type == "post-tool-use":
        result = handle_post_tool_use(payload, agent_id)
    elif hook_type == "stop":
        result = handle_stop(payload, agent_id)
    else:
        print(f"Unknown hook type: {hook_type}", file=sys.stderr)
        return 1

    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())