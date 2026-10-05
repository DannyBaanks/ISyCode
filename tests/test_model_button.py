"""M-UX3.1: current model shown inline in the composer command bar.

The button is a pure presentation shortcut: it opens the existing provider
selector and never changes provider, model, or grants by itself.
"""
import pytest

from isycode.tui import TUIApp


@pytest.mark.asyncio
async def test_model_button_visible_with_current_model():
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        button = app.query_one("#model-button")
        assert button.display is True
        label = str(button.label)
        assert label.endswith("▾")
        assert len(label) > 2


@pytest.mark.asyncio
async def test_model_button_opens_provider_selector(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.click("#model-button")
        await pilot.pause()
        assert app._menu_mode == "providers"


@pytest.mark.asyncio
async def test_model_button_label_falls_back_without_provider(monkeypatch):
    from isycode import tui_app_providers as providers_mixin
    monkeypatch.setattr(providers_mixin, "selected_provider_name",
                        lambda: (_ for _ in ()).throw(providers_mixin.ConfigurationError("nope")))
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        assert app._model_button_label() == "Model ▾"
