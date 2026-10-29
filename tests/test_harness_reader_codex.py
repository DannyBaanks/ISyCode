from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.codex import read_root


def test_codex_reader_maps_seed_without_auth_or_sqlite():
    settings, skipped = read_root(FIXTURES / "codex")
    ids = semantic_ids(settings)
    assert {"default_model", "reasoning_effort", "folder_trust", "mcp_server_list",
            "enabled_plugins", "user_skills", "provider_endpoint", "project_instructions",
            "prior_transcript"} <= ids
    assert row_for(settings, "default_model").display_value == "gpt-test"
    assert row_for(settings, "provider_endpoint").display_value == "present"
    assert any(row.pointer == "approvals_reviewer" and row.semantic_id is None for row in settings)
    assert any(item.relative_path == "auth.json" for item in skipped)
