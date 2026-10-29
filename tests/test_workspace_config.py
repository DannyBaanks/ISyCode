"""Pure schema validation for per-workspace ISyCode preferences."""
from __future__ import annotations

import json

import pytest

from isycode.workspace_config import parse_workspace_config, resolve_workspace_preferences


def payload(**fields) -> bytes:
    return json.dumps({"version": 1, **fields}).encode("utf-8")


def test_v1_accepts_only_supported_non_authority_preferences():
    result = parse_workspace_config(payload(
        default_role={"kind": "agents", "name": "reviewer"},
        agent_steps=25, answer_tokens=16384, chat_token_budget=50000,
    ))

    assert result.valid
    assert result.values == {
        "default_role": {"kind": "agents", "name": "reviewer"},
        "agent_steps": 25,
        "answer_tokens": 16384,
        "chat_token_budget": 50000,
    }


def test_missing_preferences_are_left_unset_for_user_defaults_to_supply():
    result = parse_workspace_config(payload())

    assert result.valid
    assert result.values == {}


def test_unknown_fields_warn_and_are_ignored():
    result = parse_workspace_config(payload(theme="dark", agent_steps=10))

    assert result.valid
    assert result.values == {"agent_steps": 10}
    assert len(result.warnings) == 1
    assert "theme" in result.warnings[0]


@pytest.mark.parametrize("raw", [
    b"not json",
    b"\xff",
    b"[]",
    b'{"version":true}',
    b'{"version":2}',
    b'{"version":1,"agent_steps":true}',
    b'{"version":1,"agent_steps":11}',
    b'{"version":1,"answer_tokens":1000}',
    b'{"version":1,"chat_token_budget":1}',
    b'{"version":1,"default_role":{"kind":"provider","name":"x"}}',
    b'{"version":1,"default_role":{"kind":"agents","name":""}}',
])
def test_malformed_or_unsupported_config_disables_all_workspace_values(raw):
    result = parse_workspace_config(raw)

    assert not result.valid
    assert result.values == {}
    assert result.error


def test_payload_over_limit_is_rejected_before_json_parsing():
    result = parse_workspace_config(b" " * (64 * 1024 + 1))

    assert not result.valid
    assert result.values == {}
    assert "size" in result.error.casefold()


def test_workspace_preferences_override_only_product_preferences():
    workspace = parse_workspace_config(payload(agent_steps=50, workspace_mode="classic"))
    result = resolve_workspace_preferences(
        {"agent_steps": 10, "answer_tokens": 4096, "workspace_mode": "security"},
        workspace,
        {"answer_tokens": 2048, "authority_grants": {"workspace.files.write": True}},
    )

    assert result == {"agent_steps": 50, "answer_tokens": 2048}


def test_invalid_workspace_config_falls_back_to_user_preferences_as_a_whole():
    workspace = parse_workspace_config(payload(agent_steps=25, answer_tokens=999))

    assert resolve_workspace_preferences(
        {"agent_steps": 10, "answer_tokens": 4096}, workspace
    ) == {"agent_steps": 10, "answer_tokens": 4096}
