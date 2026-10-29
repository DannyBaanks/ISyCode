"""Choosing a provider without a key asks for it, with the page that creates it."""
import asyncio
from pathlib import Path
from typing import ClassVar

import pytest
from textual.app import App
from textual.widgets import Button, Input, Static

from isycode.localization import SUPPORTED_LOCALES, configure_locale, current_locale
from isycode.providers import KEY_NOTES, KEY_PAGES
from isycode.tui import TUIApp
from isycode.tui_screens_grants import ProviderKeyScreen
from test_daily_tui import configure

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "isycode"


class Host(App):
    CSS_PATH: ClassVar[list[Path]] = [PACKAGE / "isycode.tcss", PACKAGE / "design.tcss"]


def _nvidia_screen(keyring=True):
    return ProviderKeyScreen("NVIDIA NIM", url=KEY_PAGES["nvidia"], note=KEY_NOTES["nvidia"],
                             env="NVIDIA_NIM_API_KEY", keyring=keyring)


def _without_nvidia_key(tmp_path, monkeypatch, *, keyring=True):
    configure(tmp_path, monkeypatch)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("ISYMOTRON_API_KEY", raising=False)
    monkeypatch.setattr("isycode.providers.credential_state", lambda _name: "missing")
    monkeypatch.setattr("isycode.providers._SESSION_KEYS", {})
    monkeypatch.setattr("isycode.tui_app_providers.keyring_available", lambda: keyring)


def test_choosing_a_provider_without_a_key_opens_the_key_dialog(tmp_path, monkeypatch, capsys):
    _without_nvidia_key(tmp_path, monkeypatch)

    async def run():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._open_provider_menu()
            app._select_menu_entry(app._entry("NVIDIA NIM", "provider", "nvidia"))
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, ProviderKeyScreen)
            assert KEY_PAGES["nvidia"] in app.screen.dialog_note()
            assert app.focused is app.screen.query_one("#provider-key-input", Input)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ProviderKeyScreen)
            assert app._models_scope != "nvidia"

    with capsys.disabled():
        asyncio.run(run())


def test_a_saved_key_continues_to_the_model_list(tmp_path, monkeypatch, capsys):
    _without_nvidia_key(tmp_path, monkeypatch)
    saved = []

    async def save(self, service, secret):
        saved.append((service, secret))
        monkeypatch.setenv("NVIDIA_NIM_API_KEY", secret)
        return True

    monkeypatch.setattr(TUIApp, "_save_key_flow", save)

    async def run():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._open_provider_menu()
            app._select_menu_entry(app._entry("NVIDIA NIM", "provider", "nvidia"))
            await pilot.pause()
            await pilot.pause()
            field = app.screen.query_one("#provider-key-input", Input)
            field.value = "nvapi-fixture-only"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert saved == [("nvidia", "nvapi-fixture-only")]
            assert app._menu_mode == "branch" and app._models_scope == "nvidia"

    with capsys.disabled():
        asyncio.run(run())


def test_a_key_in_the_environment_goes_straight_to_models(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nvapi-fixture-only")

    async def run():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._open_provider_menu()
            app._select_menu_entry(app._entry("NVIDIA NIM", "provider", "nvidia"))
            await pilot.pause()
            assert not isinstance(app.screen, ProviderKeyScreen)
            assert app._menu_mode == "branch" and app._models_scope == "nvidia"

    with capsys.disabled():
        asyncio.run(run())


def test_api_key_settings_offer_every_keyed_provider(tmp_path, monkeypatch, capsys):
    _without_nvidia_key(tmp_path, monkeypatch)

    async def run():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._open_credentials_menu()
            services = [entry["value"] for entry in app._menu_entries
                        if entry["kind"] == "credential_add"]
            assert services[0] == "openai"          # the selected provider comes first
            assert {"nvidia", "anthropic", "groq"} <= set(services)
            assert "ollama" not in services and "chatgpt" not in services
            app._select_menu_entry(next(entry for entry in app._menu_entries
                                        if entry["kind"] == "credential_add"
                                        and entry["value"] == "nvidia"))
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, ProviderKeyScreen)

    with capsys.disabled():
        asyncio.run(run())


def test_dialog_needs_a_key_and_clears_the_field():
    async def run():
        app = Host()
        async with app.run_test(size=(100, 30)) as pilot:
            results = []
            screen = _nvidia_screen()
            app.push_screen(screen, results.append)
            await pilot.pause()
            field = screen.query_one("#provider-key-input", Input)
            assert app.focused is field and field.password
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is screen and results == []
            assert str(screen.query_one("#provider-key-error", Static).render())
            field.value = "  nvapi-fixture-only  "
            await pilot.click("#provider-key-save")
            await pilot.pause()
            assert results == ["nvapi-fixture-only"]
            assert field.value == ""

    asyncio.run(run())


def test_dialog_actions_are_reachable_by_keyboard():
    async def run():
        app = Host()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = _nvidia_screen()
            app.push_screen(screen)
            await pilot.pause()
            seen = set()
            for _ in range(4):
                await pilot.press("tab")
                await pilot.pause()
                if isinstance(app.focused, Button):
                    seen.add(app.focused.id)
            assert seen == {"provider-key-cancel", "provider-key-open", "provider-key-save"}
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is not screen

    asyncio.run(run())


@pytest.mark.parametrize("keyring", [True, False])
@pytest.mark.parametrize("size", [(80, 24), (100, 30)])
def test_dialog_fits_every_locale(size, keyring):
    width, height = size
    previous = current_locale()

    async def run():
        app = Host()
        async with app.run_test(size=size) as pilot:
            for locale in SUPPORTED_LOCALES:
                configure_locale(locale)
                screen = _nvidia_screen(keyring)
                app.push_screen(screen)
                await pilot.pause()
                await pilot.pause()
                card = screen.query_one(".isy-dialog-card").region
                assert card.right <= width and card.bottom <= height, (locale, card)
                for widget in (screen.query_one("#provider-key-input"), *screen.query(Button)):
                    assert card.contains_region(widget.region), (locale, widget.id, widget.region)
                app.pop_screen()
                await pilot.pause()

    try:
        asyncio.run(run())
    finally:
        configure_locale(previous)


def test_without_a_keyring_the_key_is_used_for_this_session_only(tmp_path, monkeypatch, capsys):
    _without_nvidia_key(tmp_path, monkeypatch, keyring=False)

    async def refuse(self, service, secret):
        raise AssertionError("nothing is saved without a keyring")

    monkeypatch.setattr(TUIApp, "_save_key_flow", refuse)

    async def run():
        from isycode import providers

        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._open_provider_menu()
            app._select_menu_entry(app._entry("NVIDIA NIM", "provider", "nvidia"))
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ProviderKeyScreen) and not screen.keyring
            assert "keyring" in screen.dialog_note()
            assert str(screen.query_one("#provider-key-save", Button).label) == "Use for this session"
            screen.query_one("#provider-key-input", Input).value = "nvapi-fixture-only"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert providers.load_provider_key("nvidia") == "nvapi-fixture-only"
            assert providers.provider_credential_state("nvidia") == "session"
            assert "nvapi-fixture-only" not in str(dict(__import__("os").environ))
            assert app._menu_mode == "branch" and app._models_scope == "nvidia"

    with capsys.disabled():
        asyncio.run(run())
