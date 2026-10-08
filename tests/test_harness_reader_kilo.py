from tests.harness_reader_helpers import FIXTURES, row_for, semantic_ids
from isycode.harness_readers.kilo import read_root


def test_kilo_reuses_the_opencode_allowlist_on_kilo_jsonc():
    settings, skipped = read_root(FIXTURES / "kilo")
    assert {"mcp_server_list", "enabled_plugins"} <= semantic_ids(settings)
    assert row_for(settings, "enabled_plugins").edge == "non_equivalent"
    assert all(row.relative_path == "kilo.jsonc" for row in settings)
    assert all("never" not in row.display_value for row in settings)
    assert skipped == []
