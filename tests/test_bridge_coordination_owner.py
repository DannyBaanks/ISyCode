"""The Bridge coordination owner: reviewed request, real gate, real receipt.

The tests never touch the user's Bridge: the client is a fake, so the owner is
exercised through its request preparation, its boundary and its receipt.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from isycode.action_runtime import (
    ActionOutcome, ActionReceipt, ProductActionGate,
)
from isycode.bridge_coordination import BridgeCoordinationOwner, session_identity
from isycode.bridge_contract import BRIDGE_OWNER_ID, OPERATIONS
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


class FakeBridgeClient:
    """Stands in for the handshake subprocess."""

    def __init__(self, identity: str, caps: str = "isycode"):
        self.identity = identity
        self.caps = caps
        self.calls: list[tuple] = []
        self.token = "identity-token"
        self.lease_tokens: dict[str, str] = {}

    def hello(self) -> str:
        self.calls.append(("hello",))
        return "HELLO ok"

    def heartbeat(self, status: str = "isycode") -> str:
        self.calls.append(("heartbeat", status))
        return "HEARTBEAT ok"

    def peek(self) -> list[dict]:
        self.calls.append(("peek",))
        return [{"seq": 7, "from": "peer", "kind": "result",
                 "topic": "demo", "payload": "done"}]

    def send(self, to: str, kind: str, topic: str, payload: str = "") -> str:
        self.calls.append(("send", to, kind, topic, payload))
        return "SENT"

    def wake(self, agent: str, message: str = "") -> str:
        self.calls.append(("wake", agent, message))
        return "WAKE ok"

    def claim(self, topic: str, ttl: int = 300, path: str = ".") -> str:
        self.calls.append(("claim", topic, ttl, path))
        return "CLAIM ok"

    def release(self, topic: str) -> str:
        self.calls.append(("release", topic))
        return "RELEASE ok"

    def goodbye(self) -> str:
        self.calls.append(("goodbye",))
        return "BYE"


@pytest.fixture()
def workspace(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return project


def _owner(project, approvals, *, identity="isycode_test_1"):
    return BridgeCoordinationOwner(project, WorkspaceAuthority(project), approvals,
                                   identity=identity)


def test_prepared_request_binds_the_exact_message(workspace):
    owner = _owner(workspace, approvals=None)
    request = owner.prepare("send", to="peer_one", topic="demo", kind="result",
                            payload="the exact text")
    assert request.action_id == "bridge.send"
    assert request.execution_owner == BRIDGE_OWNER_ID
    assert request.target == "peer_one"
    assert request.parameters["payload"] == "the exact text"
    assert request.parameters["operation"] == "send"
    assert set(request.parameters) == OPERATIONS["send"]
    # The digest covers the recipient and the text, so an approval cannot be
    # reused for a different message.
    other = owner.prepare("send", to="peer_one", topic="demo", kind="result",
                          payload="another text")
    assert request.digest != other.digest


def test_operation_table_matches_the_catalog():
    from isycode.actions import ACTION_BY_ID
    from isycode.bridge_contract import OPERATION_ACTIONS
    for operation, action in OPERATION_ACTIONS.items():
        assert action in ACTION_BY_ID, operation
    assert set(OPERATIONS) == set(OPERATION_ACTIONS)


def test_owner_denies_without_a_grant(workspace):
    owner = _owner(workspace, approvals=None)
    request = owner.prepare("send", to="peer_one", topic="demo", kind="result",
                            payload="hello")
    outcome = owner.execute(request)
    assert outcome.decision == "DENY"
    assert outcome.receipt is None


def test_owner_refuses_a_request_that_changed_after_review(workspace):
    owner = _owner(workspace, approvals=None)
    request = owner.prepare("send", to="peer_one", topic="demo", kind="result",
                            payload="hello")
    tampered = ActionRequest(
        request.action_id, request.workspace_root, "peer_two",
        dict(request.parameters, payload="something else"),
        execution_owner=BRIDGE_OWNER_ID)
    outcome = owner.execute(tampered)
    assert outcome.decision == "DENY"
    assert "changed after review" in outcome.reason


def test_boundary_rejects_a_lease_outside_the_workspace(workspace):
    from isycode.action_runtime import BridgeCoordinationSystembility
    owner = _owner(workspace, approvals=None)
    request = owner.prepare("lease.claim", topic="demo", ttl=300, path="../elsewhere")
    decision = BridgeCoordinationSystembility().evaluate(request, None)
    assert decision.passed is False
    assert "outside the authorized workspace" in decision.reason


def test_boundary_rejects_an_unknown_recipient(workspace):
    from isycode.action_runtime import BridgeCoordinationSystembility
    owner = _owner(workspace, approvals=None)
    request = owner.prepare("send", to="not a valid identity", topic="demo",
                            kind="result", payload="hello")
    decision = BridgeCoordinationSystembility().evaluate(request, None)
    assert decision.passed is False
    assert "registered identity" in decision.reason


def test_boundary_rejects_an_unexpected_parameter(workspace):
    from isycode.action_runtime import BridgeCoordinationSystembility
    owner = _owner(workspace, approvals=None)
    request = owner.prepare("send", to="peer_one", topic="demo", kind="result",
                            payload="hello")
    tampered = ActionRequest(
        request.action_id, request.workspace_root, request.target,
        dict(request.parameters, extra="value"), execution_owner=BRIDGE_OWNER_ID)
    decision = BridgeCoordinationSystembility().evaluate(tampered, None)
    assert decision.passed is False


def test_send_runs_the_handshake_and_journals_a_receipt(workspace, monkeypatch):
    client = FakeBridgeClient("isycode_test_1")
    monkeypatch.setattr("isycode.bridge_coordination.bridge_client",
                        lambda identity, caps="isycode": client)
    authority = WorkspaceAuthority(workspace)
    authority.set_grant("bridge.send", enabled=True, targets=["*"])
    owner = BridgeCoordinationOwner(workspace, authority, approvals=None,
                                    identity="isycode_test_1")
    request = owner.prepare("send", to="peer_one", topic="demo", kind="result",
                            payload="hello there")
    from isycode.approvals import ActionApprovalStore
    approvals = ActionApprovalStore()
    owner.approvals = approvals
    outcome = owner.execute(request, approvals.issue(request))
    assert outcome.decision == "ALLOW", outcome.reason
    assert isinstance(outcome.receipt, ActionReceipt)
    assert outcome.receipt.verify(request, outcome.text)
    assert ("send", "peer_one", "result", "demo", "hello there") in client.calls


def test_identity_is_unique_per_process():
    first = session_identity()
    second = session_identity()
    assert first != second
    assert first.startswith("isycode_")


def test_gate_rejects_a_bridge_request_from_another_owner(workspace):
    gate = ProductActionGate(workspace, WorkspaceAuthority(workspace),
                              owner_id=BRIDGE_OWNER_ID)
    request = ActionRequest("bridge.send", workspace, "peer_one", {},
                            execution_owner="workspace_read")
    _authority, decision = gate.authorize(request)
    assert decision.allowed is False
    assert any("different execution owner" in check.reason for check in decision.checks)


def test_owner_is_not_constructed_outside_the_bridge_module():
    """The identity token stays inside the bridge module."""
    import ast
    package = Path(__file__).resolve().parents[1] / "src" / "isycode"
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", "")
            if name == "BridgeClient" and path.name != "bridge.py":
                raise AssertionError(f"BridgeClient is constructed in {path.name}")
    assert hashlib.sha256(b"bridge").hexdigest()
