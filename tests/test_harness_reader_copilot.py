from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.copilot import read_root


def test_copilot_fixture_reader_strips_jsonc_comments_without_copying_trusted_folders():
    settings, skipped = read_root(FIXTURES / "copilot")
    assert "folder_trust" in semantic_ids(settings)
    assert row_for(settings, "folder_trust").edge == "non_equivalent"
    assert row_for(settings, "folder_trust").display_value == "1 trusted folder"
    assert any(item.relative_path == "logs/" for item in skipped)
