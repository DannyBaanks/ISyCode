from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.crush import read_root


def test_crush_reader_accepts_any_unlocked_root_and_never_exposes_env_values():
    settings, skipped = read_root(FIXTURES / "crush")
    assert {"lsp_configured_command", "mcp_server_list", "default_model", "prior_transcript"} <= semantic_ids(settings)
    model = row_for(settings, "default_model")
    assert model.provider_id == "openai" and model.model_id == "gpt-test"
    assert all("TOKEN" not in row.display_value and "never" not in row.display_value for row in settings)
    assert any(item.relative_path == "providers.json" for item in skipped)
