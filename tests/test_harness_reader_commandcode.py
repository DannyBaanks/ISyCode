from tests.harness_reader_helpers import FIXTURES, row_for, semantic_ids
from isycode.harness_readers.commandcode import read_root


def test_commandcode_maps_model_effort_and_counts_only_conversation_files():
    settings, skipped = read_root(FIXTURES / "commandcode")
    assert {"default_model", "reasoning_effort", "prior_transcript"} <= semantic_ids(settings)
    model = row_for(settings, "default_model")
    assert (model.provider_id, model.model_id) == ("fake-provider", "fake/model-1")
    assert row_for(settings, "reasoning_effort").display_value == "high"
    # session.checkpoints.jsonl is a file snapshot, not a conversation
    assert row_for(settings, "prior_transcript").display_value == "1 transcript file"
    assert {(s.relative_path, s.reason) for s in skipped} >= {("auth.json", "secret"), ("history.jsonl", "unknown")}
    assert all("never" not in row.display_value for row in settings)
