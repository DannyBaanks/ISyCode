from isycode.harness_graph import (
    CATALOG_IDS,
    SEED_OPTIONS,
    Gap,
    HarnessSetting,
    copyable_default_model,
    gap_status,
    present_by_semantic,
)


def test_catalog_is_the_reviewed_fifteen_in_order():
    assert CATALOG_IDS == (
        "crush", "qwen", "opencode", "claude", "codex", "grok", "hermes",
        "fx", "openclaw", "pi", "kimi", "cursor", "copilot", "commandcode", "kilo",
    )


def test_gap_rule_uses_four_harnesses_and_never_counts_unmapped_or_secret():
    option = SEED_OPTIONS["user_skills"]
    assert gap_status(option, {"claude", "codex", "hermes"}).status == "WATCH"
    gap = gap_status(option, {"claude", "codex", "hermes", "openclaw"})
    assert gap == Gap("user_skills", ("claude", "codex", "hermes", "openclaw"), "absent", "ADD")
    assert gap_status(SEED_OPTIONS["provider_endpoint"], {"a", "b", "c", "d"}).status == "DO_NOT_MERGE"
    assert gap_status(SEED_OPTIONS["web_fetch"], set()).status == "WATCH"
    assert gap_status(SEED_OPTIONS["secret_skip"], {"codex"}) is None
    assert gap_status(option, {"claude", "codex", "hermes", "openclaw"}, ignored=frozenset({"user_skills"})) is None


def test_present_counts_each_harness_once_and_drops_unmapped_and_non_equivalent_semantics():
    rows = [
        HarnessSetting("codex", "config.toml", "model", "str", "default_model", "same"),
        HarnessSetting("codex", "config.toml", "model2", "str", "default_model", "same"),
        HarnessSetting("grok", "config.toml", "ui.permission_mode", "str", None, "unmapped"),
        HarnessSetting("hermes", "config.yaml", "model.default", "str", "default_model", "same"),
    ]
    assert present_by_semantic(rows)["default_model"] == {"codex", "hermes"}
    assert None not in present_by_semantic(rows)


def test_non_equivalent_opencode_plugin_row_can_be_displayed_without_counting_toward_n():
    rows = [
        HarnessSetting("claude", "settings.json", "enabledPlugins", "object",
                       "enabled_plugins", "same"),
        HarnessSetting("opencode", "opencode.jsonc", "plugin[]", "list",
                       "enabled_plugins", "non_equivalent", counts_toward_n=False),
    ]
    assert present_by_semantic(rows)["enabled_plugins"] == {"claude"}


def test_default_model_copy_guard_requires_exact_preset_and_safe_model_id():
    assert copyable_default_model("openai", "gpt-5.6-sol", preset_ids={"openai", "anthropic"})
    assert not copyable_default_model("gemini", "gemini-4", preset_ids={"google"})
    assert not copyable_default_model("managed:kimi-code", "kimi", preset_ids={"openai"})
    assert not copyable_default_model("openai", "bad model with spaces", preset_ids={"openai"})
    assert not copyable_default_model("openai", "x" * 257, preset_ids={"openai"})


def test_reviewed_seed_has_separate_web_nodes_and_expected_targets():
    assert SEED_OPTIONS["web_fetch"].isycode_target == "src/isycode/web_fetch.py:WebFetchOwner.execute"
    assert SEED_OPTIONS["web_search"].isycode_target == "absent"
    assert SEED_OPTIONS["default_model"].isycode_target == "src/isycode/providers.py:save_provider_selection"
    assert SEED_OPTIONS["reasoning_effort"].isycode_target == "src/isycode/providers.py:Provider.reasoning_effort"
    assert SEED_OPTIONS["folder_trust"].transfer == "non_transferable"
