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


@pytest.mark.parametrize("provider", ["isyco-web", "not-a-provider"])
def test_chat_product_bridges_cannot_serve_gus(state, provider):
    assert not check_gus_model(provider, "any").allowed


def test_chatgpt_subscription_and_catalog_tool_models_can_serve_gus(state):
    assert check_gus_model("chatgpt", "auto").allowed
    # Preset without default supports_tools (google/openrouter) still allows tool_call=True catalog models
    check = check_gus_model("google", "gemini-2.5-pro")
    assert check.allowed


def test_a_stored_slot_that_no_longer_fits_is_refused(state, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    save_model_slot("gus", "openai", "fixture-model")
    _window("openai", "fixture-model", 8_192)
    with pytest.raises(GusSlotError, match="below 32k"):
        gus_provider()


def test_only_providers_with_ready_credentials_are_offered(state, monkeypatch):
    ready = {
        "nvidia": "stored",
        "nebius": "legacy",
        "openai": "saved",
        "chatgpt": "subscription",
        "ollama": "optional",
        "anthropic": "missing",
        "isyco-web": "optional",
    }
    monkeypatch.setattr(gus_slot, "provider_credential_state", lambda name: ready.get(name, "missing"))
    providers = gus_slot.gus_providers()
    assert providers == ["nvidia", "openai", "chatgpt", "nebius", "ollama"]


def test_settings_offer_the_gus_model_in_every_workspace(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    configure(tmp_path, monkeypatch)
    _window("openai", "gpt-6-luna", 400_000)
    _window("openai", "tiny-fixture", 8_192)
    monkeypatch.setattr(
        gus_slot,
        "provider_credential_state",
        lambda name: {"openai": "saved", "nvidia": "stored", "chatgpt": "subscription"}.get(name, "missing"),
    )
    monkeypatch.setattr(gus_slot, "custom_models", lambda provider: ["tiny-fixture"])

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            app._open_settings_menu()
            await pilot.pause()
            # ADR 0015: the GUS model is chosen here even outside an ISyCode checkout.
            gus = next(entry for entry in app._menu_entries if entry["kind"] == "gus_slot_open")
            assert "not set" in gus["label"]
            app._open_gus_slot_menu()
            offered = [e["value"] for e in app._menu_entries if e["kind"] == "gus_slot_provider"]
            for expected in ("nvidia", "openai", "chatgpt", "anthropic", "google", "openrouter", "ollama"):
                assert expected in offered
            assert "isyco-web" not in offered
            by_provider = {e["value"]: e for e in app._menu_entries if e["kind"] == "gus_slot_provider"}
            assert by_provider["nvidia"]["label"].startswith("✓")
            assert by_provider["chatgpt"]["label"].startswith("✓")
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


def test_gus_provider_selection_connects_missing_key_without_changing_chat_provider(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    from isycode.providers import selected_provider_name
    from isycode.tui import TUIApp
    from isycode.tui_screens_harness import ModelsScreen
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-chat-key")
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setattr("isycode.tui_app_providers.keyring_available", lambda: False)

    async def fake_await_screen(self, screen):
        return "test-anthropic-key"

    monkeypatch.setattr(TUIApp, "_await_screen", fake_await_screen)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            app._open_gus_provider("anthropic")
            # The scoped models screen is pushed from the key-connect worker; on a
            # slow runner a single pause finds the push scheduled and the picker
            # not yet composed. Wait for the screen and its controls, as its
            # sibling test does, instead of assuming one frame was enough.
            async def until_picker_ready():
                for _ in range(200):
                    await pilot.pause(.05)
                    screen = next((s for s in app.screen_stack
                                   if isinstance(s, ModelsScreen)), None)
                    if screen is not None and screen.query("#models-add-input"):
                        return True
                return False
            assert await until_picker_ready()
            assert selected_provider_name() == "openai"
            assert gus_slot.provider_credential_state("anthropic") == "session"
            assert app._models_target == "gus" and app._models_scope == "anthropic"

    with capsys.disabled():
        asyncio.run(scenario())


def test_an_unknown_window_is_planned_as_the_floor_not_as_128k(state):
    check = check_gus_model("ollama", "qwen3:32b")
    assert check.window is None and gus_slot.planning_window(check) == 32_000
    _window("openai", "fixture-model", 200_000)
    assert gus_slot.planning_window(check_gus_model("openai", "fixture-model")) == 200_000


def test_gus_provider_opens_models_screen_with_refresh_add_and_saves_only_gus_slot(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    from isycode.providers import selected_provider_name
    from isycode.tui import TUIApp
    from isycode.tui_screens_harness import ModelsScreen
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-chat-key")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    _window("nvidia", "nvidia/custom-gus-model", 131_072)
    monkeypatch.setattr(TUIApp, "_load_account_models", lambda self, name=None: asyncio.sleep(0))

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            app._open_gus_provider("nvidia")
            await pilot.pause()
            await pilot.pause()
            screen = next((s for s in app.screen_stack if isinstance(s, ModelsScreen)), None)
            assert screen is not None
            assert screen.provider_scope == "nvidia"
            assert app._models_target == "gus"
            assert any(e["kind"] == "model_list" and e["value"] == "nvidia" for e in screen.entries)
            assert screen.query_one("#models-add-input") is not None
            assert screen.query_one("#models-add-button") is not None
            screen.query_one("#models-add-input").value = "nvidia/custom-gus-model"
            screen._add_custom_model()
            await pilot.pause()
            assert screen.selected_model_value == "nvidia|nvidia/custom-gus-model"
            screen.dismiss({"kind": "model", "value": "nvidia|nvidia/custom-gus-model"})
            await pilot.pause()
            assert model_slot("gus") == {"provider": "nvidia", "model": "nvidia/custom-gus-model"}
            assert selected_provider_name() == "openai"
            assert getattr(app, "_models_target", "chat") == "chat"

    with capsys.disabled():
        asyncio.run(scenario())


def test_gus_screen_top_right_provider_button_updates_model_in_place(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    from isycode.gus_roots import GusRoots
    from isycode.tui import TUIApp
    from isycode.tui_screens_gus import GusProviderPickerScreen, GusScreen
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "test-nvidia")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    _window("nvidia", "nvidia/nemotron-3-ultra-550b-a55b", 1_000_000)
    save_gus_model("openai", "gpt-6-luna")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            roots = GusRoots(tmp_path)

            async def pick():
                save_gus_model("nvidia", "nvidia/nemotron-3-ultra-550b-a55b")
                return app._gus_slot_label()

            screen = GusScreen(roots, app._gus_slot_label(), pick_provider=pick)
            app.push_screen(screen)
            await pilot.pause()
            btn = screen.query_one("#gus-provider")
            assert btn is not None
            screen.dismiss_action("gus-provider")
            await pilot.pause()
            await pilot.pause()
            assert "NVIDIA NIM / nvidia/nemotron-3-ultra-550b-a55b" in screen.model_label
            assert any("NVIDIA NIM / nvidia/nemotron-3-ultra-550b-a55b" in str(t.render())
                       for t in screen.query(".isy-dialog-title"))

    with capsys.disabled():
        asyncio.run(scenario())
