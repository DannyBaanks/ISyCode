"""The Bridge coordination contract, shared by the owner and the boundary.

Kept free of product imports so the action runtime and the owner can both
read the same operation table without importing each other.
"""
from __future__ import annotations

import re

IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")
MAX_TOPIC_CHARS = 120
MAX_PAYLOAD_CHARS = 2000
MAX_MESSAGE_CHARS = 2000
MAX_KIND_CHARS = 32
MAX_TTL_SECONDS = 3600

# operation -> the exact parameter set the boundary accepts.
OPERATIONS = {
    "connect": frozenset({"executable", "handshake", "sha256", "operation"}),
    "peek": frozenset({"executable", "handshake", "sha256", "operation"}),
    "send": frozenset({"executable", "handshake", "sha256", "operation",
                       "to", "topic", "kind", "payload"}),
    "wake": frozenset({"executable", "handshake", "sha256", "operation",
                        "to", "message"}),
    "lease.claim": frozenset({"executable", "handshake", "sha256", "operation",
                               "topic", "ttl", "path"}),
    "lease.release": frozenset({"executable", "handshake", "sha256", "operation",
                                "topic"}),
}

OPERATION_ACTIONS = {
    "connect": "bridge.connect",
    "peek": "bridge.peek",
    "send": "bridge.send",
    "wake": "bridge.wake",
    "lease.claim": "bridge.lease.claim",
    "lease.release": "bridge.lease.release",
}

BRIDGE_OWNER_ID = "bridge_coordination"


# The Bridge is a local, file-backed coordination protocol. Its request target
# is the peer a message addresses, the topic a lease covers, or the bridge
# itself for a session operation.
BRIDGE_TARGET = "bridge"
BRIDGE_PEER_ACTIONS = frozenset({"bridge.send", "bridge.wake"})
BRIDGE_COORDINATION_ACTIONS = frozenset(OPERATION_ACTIONS.values())
ANY_PEER = "*"


def operation_target(operation: str, parameters: dict) -> str:
    """The reviewed target of one Bridge operation."""
    if operation in {"send", "wake"}:
        return str(parameters.get("to") or "")
    if operation in {"lease.claim", "lease.release"}:
        return str(parameters.get("topic") or "")
    return BRIDGE_TARGET
