from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from isycode.security import (
    ACTION_BY_ID,
    ActionRequest,
    AuthorityDecision,
    IsySentinel,
    SystembilityResult,
)
from isycode.isysentinel import IsySentinel as PublicIsySentinel


class StaticSystembility:
    def __init__(self, name, result, calls=None):
        self.name = name
        self.result = result
        self.calls = calls

    def evaluate(self, request, authority):
        if self.calls is not None:
            self.calls.append(self.name)
        return self.result


def request(root, action="workspace.files.read"):
    return ActionRequest(
        action_id=action,
        workspace_root=root,
        target="src/main.py",
        parameters={"line": 4},
    )


def grant_for(action):
    return AuthorityDecision(True, "grant-1", "explicit grant", action.digest)


def test_sentinel_allows_only_explicit_authority_and_passing_systembilities(tmp_path):
    sentinel = IsySentinel((StaticSystembility(
        "workspace-boundary", SystembilityResult("workspace-boundary", True, "inside root")
    ),))

    action = request(tmp_path)
    decision = sentinel.evaluate(action, grant_for(action))

    assert decision.status == "ALLOW"
    assert decision.action_id == "workspace.files.read"
    assert [check.name for check in decision.checks[:3]] == [
        "KnownAction", "Authority", "SystembilitySet"
    ]


def test_sentinel_denies_when_no_systembilities_are_configured(tmp_path):
    decision = IsySentinel(()).evaluate(
        request(tmp_path), grant_for(request(tmp_path))
    )

    assert decision.status == "DENY"
    assert any(check.name == "SystembilitySet" and not check.passed for check in decision.checks)


def test_sentinel_evaluates_every_systembility_after_a_failure(tmp_path):
    calls = []
    checks = (
        StaticSystembility("first", SystembilityResult("first", False, "blocked"), calls),
        StaticSystembility("second", SystembilityResult("second", True, "checked"), calls),
    )

    decision = IsySentinel(checks).evaluate(
        request(tmp_path), grant_for(request(tmp_path))
    )

    assert calls == ["first", "second"]
    assert decision.status == "DENY"
    assert [check.name for check in decision.checks] == [
        "KnownAction", "Authority", "SystembilitySet", "first", "second"
    ]


def test_sentinel_converts_systembility_exception_to_deny_and_continues(tmp_path):
    calls = []

    class Exploding:
        def evaluate(self, request, authority):
            calls.append("exploding")
            raise RuntimeError("secret detail must not leak")

    checks = (Exploding(), StaticSystembility(
        "second", SystembilityResult("second", True, "checked"), calls
    ))
    decision = IsySentinel(checks).evaluate(
        request(tmp_path), grant_for(request(tmp_path))
    )

    assert calls == ["exploding", "second"]
    assert decision.status == "DENY"
    assert "secret detail" not in repr(decision)


def test_unknown_action_denies_even_if_authority_and_checks_allow(tmp_path):
    decision = IsySentinel((StaticSystembility(
        "check", SystembilityResult("check", True, "ok")
    ),)).evaluate(request(tmp_path, "made.up.action"), grant_for(request(tmp_path, "made.up.action")))

    assert decision.status == "DENY"
    assert any(check.name == "KnownAction" and not check.passed for check in decision.checks)


def test_action_request_copies_and_freezes_nested_parameters():
    parameters = {"path": "src/main.py", "options": {"limit": 3}}
    root = Path.cwd()
    action = ActionRequest("workspace.files.read", root, parameters=parameters)
    parameters["options"]["limit"] = 99

    assert action.parameters["options"]["limit"] == 3
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        action.parameters["options"]["limit"] = 100
    with pytest.raises(FrozenInstanceError):
        action.action_id = "workspace.files.delete"


def test_catalog_is_unique_and_contains_every_registered_action():
    assert ACTION_BY_ID["workspace.files.read"].id == "workspace.files.read"
    assert len(ACTION_BY_ID) >= 40


def test_public_isysentinel_is_the_pure_aggregator_not_the_policy_store():
    assert PublicIsySentinel is IsySentinel
    assert not hasattr(PublicIsySentinel, "issue_approval")
    assert not hasattr(PublicIsySentinel, "set_permission")
