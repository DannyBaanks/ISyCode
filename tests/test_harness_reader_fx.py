from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.fx import read_root


def test_fx_reader_separates_default_and_session_model_and_hides_credentials():
    settings, skipped = read_root(FIXTURES / "fx")
    ids = semantic_ids(settings)
    assert {"default_model", "reasoning_effort", "session_model", "prior_transcript", "shell_approval"} <= ids
    assert row_for(settings, "default_model").provider_id == "openai"
    assert all("DO_NOT_COPY" not in row.display_value for row in settings)
    assert any(item.relative_path == "settings.json#credential_source" for item in skipped)
