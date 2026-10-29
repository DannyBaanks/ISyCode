from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.cursor import read_root


def test_cursor_reader_keeps_layout_out_of_theme_and_counts_permissions_only():
    settings, skipped = read_root(FIXTURES / "cursor")
    ids = semantic_ids(settings)
    assert {"vim_mode", "display_layout", "ui_notifications", "ui_hints",
            "explore_subagent_model", "permission_rules", "approval_mode", "sandbox_policy",
            "auto_accept_web_search", "run_everything_streak"} <= ids
    assert "ui_theme" not in ids and "default_model" not in ids and "prior_transcript" not in ids
    assert row_for(settings, "permission_rules").display_value == "allow 1 · deny 0"
    assert any(item.relative_path == "statsig-cache.json" for item in skipped)
