import time
from unittest.mock import patch

import pytest

from isycode.approvals import APPROVAL_MODES, ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest


@pytest.fixture
def sample_request(tmp_path):
    return ActionRequest(
        action_id="fs.file.write",
        workspace_root=tmp_path,
        target="file.txt",
        parameters={"content": "hello"},
        execution_owner="fs_owner",
    )


@pytest.fixture
def other_request(tmp_path):
    return ActionRequest(
        action_id="fs.file.delete",
        workspace_root=tmp_path,
        target="file.txt",
        parameters={},
        execution_owner="fs_owner",
    )


def test_approval_modes():
    assert APPROVAL_MODES == {"user", "delegated"}


def test_issue_and_consume_success(sample_request):
    store = ActionApprovalStore()
    approval = store.issue(sample_request, ttl_seconds=30.0, mode="user")

    assert isinstance(approval, ActionApproval)
    assert approval.request_digest == sample_request.digest
    assert approval.mode == "user"

    # Consuming the approval succeeds
    assert store.consume(sample_request, approval) is True

    # Consuming a second time fails (one-use token)
    assert store.consume(sample_request, approval) is False


def test_consume_with_different_request(sample_request, other_request):
    store = ActionApprovalStore()
    approval = store.issue(sample_request)

    # Consuming with a different request fails
    assert store.consume(other_request, approval) is False


def test_consume_invalid_inputs(sample_request):
    store = ActionApprovalStore()
    assert store.consume("not_a_request", None) is False  # type: ignore[arg-type]
    assert store.consume(sample_request, "not_an_approval") is False  # type: ignore[arg-type]


def test_issue_clamping_and_validation(sample_request):
    store = ActionApprovalStore()

    # Mode validation
    with pytest.raises(ValueError, match="Approval mode must be 'user' or 'delegated'"):
        store.issue(sample_request, mode="invalid_mode")

    # Request validation
    with pytest.raises(TypeError, match="Approval requires an immutable ActionRequest"):
        store.issue("not_a_request")  # type: ignore[arg-type]

    # Non-finite ttl
    with pytest.raises(ValueError, match="Approval lifetime must be a finite number of seconds"):
        store.issue(sample_request, ttl_seconds=float("inf"))

    with pytest.raises(ValueError, match="Approval lifetime must be a finite number of seconds"):
        store.issue(sample_request, ttl_seconds="invalid_num")  # type: ignore[arg-type]

    # TTL clamping: min 1.0, max 120.0
    now = time.monotonic()
    appr_min = store.issue(sample_request, ttl_seconds=0.1)
    assert appr_min.expires_at >= now + 1.0

    appr_max = store.issue(sample_request, ttl_seconds=999.0)
    assert appr_max.expires_at <= now + 120.5


def test_consume_expired(sample_request):
    store = ActionApprovalStore()
    approval = store.issue(sample_request, ttl_seconds=1.0)

    # Fast forward time to simulate expiration
    with patch("time.monotonic", return_value=time.monotonic() + 10.0):
        assert store.consume(sample_request, approval) is False


def test_clear(sample_request):
    store = ActionApprovalStore()
    store.issue(sample_request)
    store.issue(sample_request)

    cleared = store.clear()
    assert cleared == 2
    assert store.clear() == 0


def test_max_pending_approvals_limit(sample_request):
    store = ActionApprovalStore()
    store.MAX_PENDING_APPROVALS = 3

    store.issue(sample_request)
    store.issue(sample_request)
    store.issue(sample_request)

    with pytest.raises(RuntimeError, match="Too many pending approvals"):
        store.issue(sample_request)
