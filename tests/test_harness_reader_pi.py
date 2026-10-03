from tests.harness_reader_helpers import FIXTURES, semantic_ids
from isycode.harness_readers.pi import read_root


def test_pi_reader_maps_theme_and_transcript_names_only():
    settings, skipped = read_root(FIXTURES / "pi")
    assert {"ui_theme", "prior_transcript"} <= semantic_ids(settings)
    assert any(item.relative_path == "agent/auth.json" for item in skipped)
    assert any(item.relative_path == "agent/models-store.json" and item.reason == "oversize" for item in skipped)
