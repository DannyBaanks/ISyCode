from tests.harness_reader_helpers import FIXTURES, semantic_ids
from isycode.harness_readers.qwen import read_root


def test_qwen_reader_lists_chat_names_without_opening_settings_or_markdown_body():
    settings, skipped = read_root(FIXTURES / "qwen")
    assert "prior_transcript" in semantic_ids(settings)
    assert "project_instructions" not in semantic_ids(settings)
    assert any(item.relative_path == "settings.json" for item in skipped)
