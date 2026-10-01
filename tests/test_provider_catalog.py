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


def test_openrouter_does_not_advertise_model_agnostic_tool_support():
    provider = Provider(name="openrouter", model="example/model", api_key="test")
    assert provider.supports_tools is False
