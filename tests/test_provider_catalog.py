import pytest

from isycode.config import load_api_key
from isycode.providers import (
    PRESETS, Provider, model_context_limit, model_slot, record_model_metadata,
    save_model_slot, save_provider_selection,
)


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


def test_model_dependent_presets_send_tools_only_after_an_explicit_opt_in(monkeypatch):
    from isycode.providers import provider_supports_tools

    monkeypatch.delenv("ISYCODE_TOOL_CALLS", raising=False)
    assert provider_supports_tools("ollama")  # the preset declares the protocol
    assert not provider_supports_tools("openrouter") and not provider_supports_tools("cerebras")
    monkeypatch.setenv("ISYCODE_TOOL_CALLS", "1")
    assert provider_supports_tools("openrouter") and provider_supports_tools("cerebras")
    assert Provider(name="openrouter", model="example/model", api_key="test").supports_tools
    assert not provider_supports_tools("not-a-provider")


def test_small_model_slot_is_typed_private_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    save_model_slot("small", "openai", "gpt-5.6-mini")

    assert model_slot("small") == {"provider": "openai", "model": "gpt-5.6-mini"}
    assert model_slot("chat") is None
    with pytest.raises(ValueError):
        save_model_slot("admin", "openai", "gpt-5.6-mini")
    with pytest.raises(ValueError):
        save_model_slot("small", "missing-provider", "x")


def test_live_model_context_window_survives_model_selection_without_accepting_bad_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    record_model_metadata("openai", "gpt-example", {"context_length": 200_000})
    assert model_context_limit("openai", "gpt-example") == (200_000, "live-catalog")
    save_provider_selection("openai", "gpt-example")
    assert model_context_limit("openai", "gpt-example") == (200_000, "live-catalog")
    record_model_metadata("openai", "gpt-example", {"context_length": True})
    assert model_context_limit("openai", "gpt-example") == (200_000, "live-catalog")


def test_nvidia_accepts_nvidia_api_key_alias_with_nim_precedence(monkeypatch, tmp_path):
    from isycode.config import credential_state
    from isycode.credentials import set_saved_secret_reader
    from isycode.diagnostics import collect_diagnostics
    from isycode.providers import load_provider_key, provider_credential_state, provider_key_envs

    set_saved_secret_reader(None)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    for var in ("NVIDIA_NIM_API_KEY", "NVIDIA_API_KEY", "ISYMOTRON_API_KEY", "ISYMOTRON_API_KEY_FILE", "ISYMOTRON_KEY_STORE"):
        monkeypatch.delenv(var, raising=False)

    assert provider_key_envs("nvidia") == ("NVIDIA_NIM_API_KEY", "NVIDIA_API_KEY")
    assert load_api_key("nvidia") == ""
    assert credential_state("nvidia") == "missing"

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-alias-key")
    assert load_api_key("nvidia") == "nvapi-alias-key"
    assert load_provider_key("nvidia") == "nvapi-alias-key"
    assert credential_state("nvidia") == "environment"
    assert provider_credential_state("nvidia") == "environment"
    assert Provider(name="nvidia").configured() is True
    assert collect_diagnostics(tmp_path)["provider"]["credential"] == "environment-present"

    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nvapi-primary-key")
    assert load_api_key("nvidia") == "nvapi-primary-key"
    assert load_provider_key("nvidia") == "nvapi-primary-key"

    # Also accepted in keys.env when env vars are unset.
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    store = tmp_path / "cfg" / "isymotron" / "keys.env"
    store.parent.mkdir(parents=True)
    store.write_text("NVIDIA_API_KEY=nvapi-stored-alias\n", encoding="utf-8")
    assert load_api_key("nvidia") == "nvapi-stored-alias"
    assert credential_state("nvidia") == "stored"
