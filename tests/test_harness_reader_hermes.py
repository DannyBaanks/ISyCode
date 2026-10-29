from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.hermes import read_root


def test_hermes_reader_keeps_skin_toolsets_and_persona_semantically_separate():
    settings, skipped = read_root(FIXTURES / "hermes")
    ids = semantic_ids(settings)
    assert {"default_model", "provider_endpoint", "reasoning_effort", "ui_skin",
            "command_allowlist", "toolset_list", "user_skills", "agent_persona",
            "user_profile_file", "prior_transcript"} <= ids
    assert "ui_theme" not in ids and "project_instructions" not in ids
    assert row_for(settings, "provider_endpoint").display_value == "present"
    assert any(row.pointer == "web.backend" and row.semantic_id is None for row in settings)
    assert any(item.relative_path == "auth.json" for item in skipped)
