import pytest

from isycode.config import load_api_key
from isycode.providers import PRESETS, Provider


@pytest.mark.parametrize(("name", "base_url", "key_env"), [
    ("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    ("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
])
def test_added_cloud_provider_preset_and_env_key(monkeypatch, tmp_path,
                                                name, base_url, key_env):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv(key_env, "test-provider-key")

    preset = PRESETS[name]
    provider = Provider(name=name, model="example/model", api_key="test-provider-key")

    assert preset["base_url"] == base_url
    assert preset["key_env"] == key_env
    assert provider.configured()
    assert provider.base_url == base_url
    assert load_api_key(name) == "test-provider-key"


def test_provider_screen_lists_wired_presets_and_unwired_names():
    from isycode.providers import PRESETS, PROVIDER_SCREEN

    groups = [group for group, _key, _label, _blurb in PROVIDER_SCREEN]
    assert groups[0] == "popular"
    assert "providers" in groups
    wired = {key for _group, key, _label, _blurb in PROVIDER_SCREEN if key}
    assert {"nvidia", "openai", "xai", "deepseek", "opencode"} <= wired
    assert wired <= set(PRESETS)
    assert set(PRESETS) - wired == {"chatgpt"}
    for key in wired:
        preset = PRESETS[key]
        assert preset.get("base_url")
        # nvidia and nebius already fall back to DEFAULT_MODEL. New rows must name one.
        assert key in {"nvidia", "nebius"} or preset.get("default_model")
    unwired = [label for _group, key, label, _blurb in PROVIDER_SCREEN if not key]
    assert "GitHub Copilot" in unwired
    assert "AWS Bedrock" in unwired
    assert "Google Vertex AI" in unwired
    assert all(label not in PRESETS for label in unwired)


def test_openrouter_does_not_advertise_model_agnostic_tool_support():
    provider = Provider(name="openrouter", model="example/model", api_key="test")
    assert provider.supports_tools is False
