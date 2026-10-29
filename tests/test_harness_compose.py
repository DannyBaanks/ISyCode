from isycode.harness_graph import repair_compose


def test_compose_is_deterministic_scoped_and_never_prompt_authority():
    first = repair_compose("user_skills", ["codex", "claude"])
    assert first == repair_compose("user_skills", ["claude", "codex", "codex", "unknown"])
    assert "not a bearer token" in first
    assert "Fresh request-bound approvals" in first
    assert first != repair_compose("user_skills", ["codex"])


def test_foreign_permissions_only_offer_native_review():
    brief = repair_compose("approval_bypass", ["claude"])
    assert "Do not import foreign permission" in brief
    assert "stop before that effect" in brief
