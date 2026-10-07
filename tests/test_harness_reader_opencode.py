from tests.harness_reader_helpers import FIXTURES, semantic_ids, row_for
from isycode.harness_readers.opencode import read_root


def test_opencode_automatic_root_is_empty_but_picked_config_is_allowlisted():
    settings, _ = read_root(FIXTURES / "opencode", automatic=True)
    assert settings == []
    settings, skipped = read_root(FIXTURES / "opencode", automatic=False)
    assert {"lsp_configured_command", "mcp_server_list", "enabled_plugins"} <= semantic_ids(settings)
    assert row_for(settings, "enabled_plugins").edge == "non_equivalent"
    assert all("never" not in row.display_value for row in settings)
