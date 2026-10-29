from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.openclaw import read_root


def test_openclaw_reader_uses_agents_file_role_and_skips_auth_and_sqlite():
    settings, skipped = read_root(FIXTURES / "openclaw")
    ids = semantic_ids(settings)
    assert {"default_model", "provider_endpoint", "enabled_plugins", "user_skills",
            "project_instructions", "agent_persona", "agent_identity", "user_profile_file"} <= ids
    assert "prior_transcript" not in ids
    assert row_for(settings, "provider_endpoint").display_value == "present"
    assert any(item.relative_path == "openclaw.json#auth" for item in skipped)
    assert any(item.relative_path == "state/openclaw.sqlite" for item in skipped)
