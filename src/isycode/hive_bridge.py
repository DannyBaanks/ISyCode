"""Best-effort lifecycle emitter for the Munder hive bridge (DannyBaanks/isyco-worlds).

isyco-worlds spawns ISyCode as a worker and, via `hive.ts`, exports two
environment variables into the agent's PTY:

  HIVE_SOCK   — path to a UNIX domain socket the hive listens on for lifecycle
                events.
  AGENT_ID    — this agent's stable id within the hive.

This module turns ISyCode's chat-loop events into the same cth-hook-shaped,
line-delimited JSON that the Claude hook shim, the OpenCode plugin, and the Pi /
proxy sidecars emit — so ISyCode becomes a first-class hive citizen
(live status + inbox-drain-on-idle) **without** ISyCo needing a plugin API of
its own. The contract this posts is verified against hive.ts's shim
consumers (`PreToolUse` / `PostToolUse` / `Stop`, with `agent_id`,
`session_id`, `tool_name`, `tool_input`).

Design rules (must never regress the TUI):
  - A NO-OP when HIVE_SOCK or AGENT_ID is absent. Stock ISyCo is entirely
    unaffected — a source-checkout run with no hive never starts a single
    thread.
  - Fire-and-forget and never blocks the event loop. The UNIX socket is
    written from a single long-lived sender thread fed by a queue, so a slow or
    absent reader cannot stall tool execution or the chat turn.
  - Every failure path is swallowed: a missing/unreachable socket, a refused
    send, marshalling errors — all return silently. The emitter must be a pure
    side channel; ISyCo's own correctness is the primary path.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import socket
import threading

# The only events the hive's shim consumers understand. Anything else is a
# programming mistake, not data to forward.
_HOOK_EVENTS = frozenset(("PreToolUse", "PostToolUse", "Stop"))

# A payload key worth recording only when it carries information. tool_input for a
# chat-model tool call is {"name": <str>, "arguments": <json str>}; we pass it
# through opaque — the hive scrubs it next to the receipt.
_SHUTDOWN_SENTINEL: tuple[None, None] = (None, None)


class HiveBridge:
    """Thread-safe, lazy, one-sender-per-process lifecycle emitter.

    Reads HIVE_SOCK / AGENT_ID from the environment per call, so a hive that
    attaches mid-run (or a test that sets/clears the vars) is honored without a
    restart. Idempotent `ensure` means every `emit` is a plain queue put — never
    a connect — once the sender is live."""

    def __init__(self) -> None:
        self._q: queue.Queue[tuple[str | None, dict]] | None = None
        self._thread: threading.Thread | None = None
        self._init_lock = threading.Lock()

    def agent_id(self) -> str | None:
        # AGENT_ID is what isyco-worlds writes; ISYCO_AGENT_ID is reserved for a
        # future standalone attach. Either makes the emitter live.
        return os.environ.get("AGENT_ID") or os.environ.get("ISYCO_AGENT_ID")

    @staticmethod
    def _session_id(app) -> str | None:
        # TUIApp._active_chat_session_id is the id of the conversation the user is
        # currently in (None for a stateless 'memory' turn). It is the same id the
        # hive would resume later, so routing Stop/inbox-drain back to it is exact.
        sid = getattr(app, "_active_chat_session_id", None)
        return sid if isinstance(sid, str) and sid else None

    @staticmethod
    def _send(payload: dict) -> None:
        path = os.environ.get("HIVE_SOCK")
        if not path or not os.path.exists(path):
            return
        try:
            data = (json.dumps(payload) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            return
        sock = None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.25)
            try:
                sock.connect(path)
                sock.sendall(data)
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
        except OSError:
            return

    def _sender(self) -> None:
        # Capture the queue once: `shutdown` may null `self._q` while this loop
        # is mid-flight, and a late `task_done`/`get` against None would kill the
        # sender thread and drop live events. `task_done` is unnecessary (nobody
        # joins the queue), so we skip it entirely to keep the hot path lock-free.
        q = self._q
        assert q is not None
        while True:
            event, payload = q.get()
            if event is None:  # shutdown sentinel
                return
            self._send(payload)

    def _ensure(self) -> bool:
        with self._init_lock:
            if self._q is not None:
                return True
            if not self.agent_id() or not os.environ.get("HIVE_SOCK"):
                # Hive isn't managing this process; stay completely inert.
                return False
            self._q = queue.Queue()
            self._thread = threading.Thread(
                target=self._sender, name="hive-bridge-sender", daemon=True
            )
            self._thread.start()
            atexit.register(self.shutdown)
            return True

    def shutdown(self) -> None:
        with self._init_lock:
            q = self._q
            self._q = None
        if q is not None:
            q.put(_SHUTDOWN_SENTINEL)

    def emit(
        self,
        event: str,
        app=None,
        *,
        tool_name: str | None = None,
        tool_input: object | None = None,
    ) -> None:
        if event not in _HOOK_EVENTS or not self._ensure():
            return
        # tool_name attaches to the per-tool hooks; Stop is a session-level idle
        # signal and carries no tool context. tool_input attaches to PreToolUse
        # only — the before half needs the args, the after half does not.
        payload: dict = {
            "agent_id": self.agent_id(),
            "session_id": self._session_id(app) if app is not None else None,
            "hook_event_name": event,
        }
        if event in ("PreToolUse", "PostToolUse") and tool_name is not None:
            payload["tool_name"] = tool_name
        if event == "PreToolUse" and tool_input is not None:
            payload["tool_input"] = tool_input
        try:
            self._q.put_nowait((event, payload))
        except Exception:
            return


# Module-level singleton. Importing the module is free; it wires up nothing
# until the first `emit` sees HIVE_SOCK + AGENT_ID.
bridge = HiveBridge()


def emit(
    event: str,
    app=None,
    *,
    tool_name: str | None = None,
    tool_input: object | None = None,
) -> None:
    """Public entry point used by the chat loop."""
    bridge.emit(event, app, tool_name=tool_name, tool_input=tool_input)
