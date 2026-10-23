"""GUS model slot (ADR 0011, MK2): its own provider/model, 32k tokens or more, no fallback."""
import asyncio

import pytest

from isycode import gus_slot
from isycode.gus_slot import GusSlotError, check_gus_model, gus_provider, save_gus_model
from isycode.providers import model_slot, record_model_metadata, save_model_slot


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("ISYCODE_TOOL_CALLS", raising=False)
    return tmp_path


def _window(provider, model, tokens):
    record_model_metadata(provider, model, {"context_length": tokens})


def test_an_empty_slot_never_falls_back_to_the_chat_model(state, monkeypatch):
    """GK2-01."""
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    save_model_slot("small", "openai", "gpt-small-fixture")
    with pytest.raises(GusSlotError, match="no model yet"):
        gus_provider()


@pytest.mark.parametrize("tokens, allowed", [(8_192, False), (31_999, False),
                                             (32_000, True), (32_768, True), (131_072, True)])
def test_the_window_floor_is_32k_tokens(state, tokens, allowed):
    """GK2-02."""
    _window("openai", "fixture-model", tokens)
    check = check_gus_model("openai", "fixture-model")
    assert check.allowed is allowed and check.window == tokens
    if not allowed:
        with pytest.raises(GusSlotError, match="below 32k"):
            save_gus_model("openai", "fixture-model")
        assert model_slot("gus") is None


def test_a_saved_model_is_what_gus_talks_to(state, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    _window("openai", "fixture-model", 200_000)
    save_gus_model("openai", "fixture-model")
    provider = gus_provider()
    assert (provider.name, provider.model) == ("openai", "fixture-model")
    assert model_slot("gus") == {"provider": "openai", "model": "fixture-model"}


def test_a_model_without_tool_calls_cannot_serve_gus(state, monkeypatch):
    monkeypatch.setattr(gus_slot, "catalog_models", lambda provider: [
        {"id": "chat-only", "name": "Chat only", "context": 200_000,
         "tool_call": False, "reasoning": False}])
    check = check_gus_model("openai", "chat-only")
    assert not check.allowed and "no tool calls" in check.reason


def test_a_local_model_keeps_an_unknown_window(state):
    check = check_gus_model("ollama", "qwen3:32b")
    assert check.allowed and check.window is None and check.source == "unknown"


def test_a_provider_without_tool_calls_cannot_serve_gus(state, monkeypatch):
    monkeypatch.setattr(gus_slot, "provider_supports_tools", lambda name: False)
    check = check_gus_model("ollama", "qwen3:32b")
    assert not check.allowed and "Tool calls are off" in check.reason


@pytest.mark.parametrize("provider", ["isyco-web", "chatgpt", "not-a-provider"])
def test_chat_product_bridges_cannot_serve_gus(state, provider):
    assert not check_gus_model(provider, "any").allowed


def test_a_stored_slot_that_no_longer_fits_is_refused(state, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    save_model_slot("gus", "openai", "fixture-model")
    _window("openai", "fixture-model", 8_192)
    with pytest.raises(GusSlotError, match="below 32k"):
        gus_provider()


def test_only_providers_with_ready_credentials_are_offered(state, monkeypatch):
    ready = {"openai": "saved", "ollama": "optional", "anthropic": "missing", "isyco-web": "optional"}
    monkeypatch.setattr(gus_slot, "provider_credential_state", lambda name: ready.get(name, "missing"))
    assert gus_slot.gus_providers() == ["openai", "ollama"]


def test_settings_offer_the_gus_model_only_in_the_isycode_repo(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    configure(tmp_path, monkeypatch)
    _window("openai", "gpt-6-luna", 400_000)
    _window("openai", "tiny-fixture", 8_192)
    monkeypatch.setattr(gus_slot, "provider_credential_state",
                        lambda name: "saved" if name == "openai" else "missing")
    monkeypatch.setattr(gus_slot, "custom_models", lambda provider: ["tiny-fixture"])

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            app._open_settings_menu()
            await pilot.pause()
            assert "gus_slot_open" not in [entry["kind"] for entry in app._menu_entries]
            app._close_menu()
            for marker in ("src/isycode/gus_role.py", "src/isycode/agents/gus.md"):
                path = app._workspace_root / marker
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            app._open_settings_menu()
            await pilot.pause()
            gus = next(entry for entry in app._menu_entries if entry["kind"] == "gus_slot_open")
            assert "not set" in gus["label"]
            app._open_gus_slot_menu()
            assert [e["value"] for e in app._menu_entries if e["kind"] == "gus_slot_provider"] == ["openai"]
            app._open_gus_models_menu("openai")
            rows = {e["value"].split("\n")[1]: e for e in app._menu_entries}
            assert rows["tiny-fixture"]["kind"] == "info" and "32k" in rows["tiny-fixture"]["detail"]
            assert rows["gpt-6-luna"]["kind"] == "gus_slot_model" and "400k" in rows["gpt-6-luna"]["label"]
            app._choose_gus_model("openai\ngpt-6-luna")
            await pilot.pause()
            assert model_slot("gus") == {"provider": "openai", "model": "gpt-6-luna"}
            assert app._menu_mode == "settings"
            assert "gpt-6-luna" in next(e["label"] for e in app._menu_entries
                                        if e["kind"] == "gus_slot_open")
            app._choose_gus_model("openai\ntiny-fixture")
            assert model_slot("gus") == {"provider": "openai", "model": "gpt-6-luna"}

    with capsys.disabled():
        asyncio.run(scenario())
