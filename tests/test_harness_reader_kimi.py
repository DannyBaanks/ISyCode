from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.kimi import read_root


def test_kimi_reader_keeps_services_out_of_web_capabilities_and_trust_nontransferable():
    settings, skipped = read_root(FIXTURES / "kimi")
    ids = semantic_ids(settings)
    assert {"default_model", "provider_endpoint", "ui_theme", "ui_notifications",
            "folder_trust", "prior_transcript"} <= ids
    assert "web_fetch" not in ids and "web_search" not in ids and "reasoning_effort" not in ids
    assert row_for(settings, "folder_trust").edge == "non_equivalent"
    assert row_for(settings, "provider_endpoint").display_value == "present"
    assert any(item.relative_path.startswith("credentials/") for item in skipped)
