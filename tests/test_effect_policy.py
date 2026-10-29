"""Effect taxonomy. Classification is not a grant."""
from pathlib import Path

import pytest

from isycode.actions import ACTION_BY_ID
from isycode.effect_policy import (
    CLASSIC_PRESET_EFFECTS, EFFECTS, POLICY_VERSION, classic_preset_ids, effect_class,
    implicit_actions, stamp,
)
from isycode.security import ActionRequest
from isycode.workspace_authority import CLASSIC_ACTIONS


def test_every_catalog_action_has_one_known_effect():
    for action_id, spec in ACTION_BY_ID.items():
        assert effect_class(action_id) in EFFECTS
        assert effect_class(action_id) == effect_class(spec.id)


def test_unknown_action_and_unknown_mode_fail_closed():
    with pytest.raises(KeyError):
        effect_class("not.a.registered.action")
    with pytest.raises(ValueError):
        implicit_actions("yolo")


def test_classic_preset_is_versioned_and_security_is_empty():
    assert classic_preset_ids() == frozenset(CLASSIC_ACTIONS)
    assert implicit_actions("classic") == frozenset(CLASSIC_ACTIONS)
    assert implicit_actions("security") == frozenset()
    for action_id in CLASSIC_ACTIONS:
        assert effect_class(action_id) in CLASSIC_PRESET_EFFECTS
    assert effect_class("clipboard.copy") == "publication"
    assert effect_class("workspace.files.read_sensitive") == "privileged_metadata"
    assert "clipboard.copy" not in implicit_actions("classic")
    assert "workspace.files.read_sensitive" not in implicit_actions("classic")


def test_stamp_binds_the_request_digest_and_policy_version(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    request = ActionRequest("workspace.files.read", root, str(root / "app.py"),
                            {"path": "app.py"}, execution_owner="workspace_read")
    bound = stamp(request)
    assert bound.policy_version == POLICY_VERSION == 1
    assert bound.request_digest == request.digest
    assert bound.action_id == "workspace.files.read"
    assert bound.effect_class == "read"
    with pytest.raises(TypeError):
        stamp(object())
