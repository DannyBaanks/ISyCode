from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.grok import read_root


def test_grok_reader_maps_reviewed_options_without_transcript_bodies():
    settings, skipped = read_root(FIXTURES / "grok")
    ids = semantic_ids(settings)
    assert {"approval_bypass", "vim_mode", "fork_secondary_model", "ui_auto_dark_theme",
            "folder_trust", "session_model", "sandbox_policy", "prior_transcript"} <= ids
    assert "reasoning_effort" not in [row.semantic_id for row in settings if "summary.json" in row.relative_path]
    assert row_for(settings, "prior_transcript").display_value == "1 transcript file"
    assert all("body must not enter graph" not in row.display_value for row in settings)
    assert any(item.relative_path == "auth.json" and item.reason == "secret" for item in skipped)
    assert any(row.pointer == "ui.permission_mode" and row.semantic_id is None for row in settings)
