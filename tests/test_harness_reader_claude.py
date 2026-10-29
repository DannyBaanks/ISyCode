from tests.harness_reader_helpers import FIXTURES, semantic_ids
from isycode.harness_readers.claude import read_root


def test_claude_reader_maps_theme_plugins_skips_hooks_and_indexes_transcripts():
    settings, skipped = read_root(FIXTURES / "claude")
    ids = semantic_ids(settings)
    assert {"ui_theme", "enabled_plugins", "approval_bypass", "hook_command",
            "prior_transcript", "user_skills"} <= ids
    assert all("secret transcript body" not in row.display_value for row in settings)
    assert any(item.relative_path == ".credentials.json" for item in skipped)
