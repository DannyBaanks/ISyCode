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

import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

# Add src to path for imports when run as script
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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

    # Check write guard for file tools
    if tool_name in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        manager = HiveManager(HiveConfig(harness_home=hive_root.parent))
        manager.ensure_hive()
        decision = manager.check_write(tool_name, tool_input, cwd, agent_id)
        if decision["deny"]:
            return {
                "decision": "deny",
                "reason": decision["reason"],
            }
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
    return {"decision": "allow"}


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