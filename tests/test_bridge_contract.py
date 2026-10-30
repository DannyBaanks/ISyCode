from isycode.bridge_contract import (
    ANY_PEER,
    BRIDGE_COORDINATION_ACTIONS,
    BRIDGE_OWNER_ID,
    BRIDGE_PEER_ACTIONS,
    BRIDGE_TARGET,
    IDENTITY_PATTERN,
    MAX_KIND_CHARS,
    MAX_MESSAGE_CHARS,
    MAX_PAYLOAD_CHARS,
    MAX_TOPIC_CHARS,
    MAX_TTL_SECONDS,
    OPERATION_ACTIONS,
    OPERATIONS,
    operation_target,
)


def test_operation_target():
    # Peer operations target recipient
    assert operation_target("send", {"to": "agent_alpha"}) == "agent_alpha"
    assert operation_target("wake", {"to": "agent_beta"}) == "agent_beta"
    assert operation_target("send", {}) == ""

    # Lease operations target topic
    assert operation_target("lease.claim", {"topic": "subsystem/auth"}) == "subsystem/auth"
    assert operation_target("lease.release", {"topic": "subsystem/auth"}) == "subsystem/auth"
    assert operation_target("lease.claim", {}) == ""

    # Session operations target the bridge itself
    assert operation_target("connect", {}) == BRIDGE_TARGET
    assert operation_target("peek", {}) == BRIDGE_TARGET
    assert operation_target("unknown_op", {}) == BRIDGE_TARGET


def test_identity_pattern():
    assert IDENTITY_PATTERN.fullmatch("agent-1") is not None
    assert IDENTITY_PATTERN.fullmatch("claude_code_0123456789abcdef") is not None
    assert IDENTITY_PATTERN.fullmatch("antigravity.subagent-42") is not None
    assert IDENTITY_PATTERN.fullmatch("a" * 64) is not None

    # Invalid cases
    assert IDENTITY_PATTERN.fullmatch("") is None
    assert IDENTITY_PATTERN.fullmatch("a" * 65) is None
    assert IDENTITY_PATTERN.fullmatch("agent with spaces") is None
    assert IDENTITY_PATTERN.fullmatch("agent@host") is None
    assert IDENTITY_PATTERN.fullmatch("path/to/agent") is None


def test_operations_consistency():
    assert set(OPERATIONS.keys()) == set(OPERATION_ACTIONS.keys())
    assert BRIDGE_COORDINATION_ACTIONS == frozenset(OPERATION_ACTIONS.values())
    assert BRIDGE_PEER_ACTIONS == {"bridge.send", "bridge.wake"}
    assert BRIDGE_PEER_ACTIONS.issubset(BRIDGE_COORDINATION_ACTIONS)
    assert BRIDGE_OWNER_ID == "bridge_coordination"
    assert ANY_PEER == "*"


def test_constants_limits():
    assert MAX_TOPIC_CHARS == 120
    assert MAX_PAYLOAD_CHARS == 2000
    assert MAX_MESSAGE_CHARS == 2000
    assert MAX_KIND_CHARS == 32
    assert MAX_TTL_SECONDS == 3600
