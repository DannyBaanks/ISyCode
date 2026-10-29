"""The composer model control opens the active provider's explicit picker."""
import pytest

from isycode.tui import TUIApp
from isycode.providers import Provider, resolved_chat_model, selected_provider_name


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
async def test_model_button_opens_chatgpt_account_model_picker(tmp_path, monkeypatch):
    from test_daily_tui import configure
    original_models = Provider.models
    root = configure(tmp_path, monkeypatch)
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.tui import ModelsScreen

    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    monkeypatch.setenv("ISYCODE_CODEX_EXECUTABLE", str(executable))
    monkeypatch.setenv("ISYCODE_PROVIDER", "chatgpt")  # post-OAuth session
    monkeypatch.setenv("ISYCODE_MODEL", "auto")
    monkeypatch.setattr(Provider, "models", original_models)
    authority = WorkspaceAuthority(root)
    from isycode.provider_auth import AUTH_HOSTS
    authority.set_grant(
        "provider.authenticate", enabled=True, targets=["chatgpt"],
        executables=[str(executable)], network_hosts=list(AUTH_HOSTS))
    authority.set_grant(
        "provider.request", enabled=True,
        network_hosts=["chatgpt.com", *AUTH_HOSTS])

    catalog_calls = []

    class AccountConnector:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def models(self):
            catalog_calls.append("chatgpt")
            return ["fixture-chat-model"]

    monkeypatch.setattr("isycode.codex_connector.CodexConnector", AccountConnector)

    async def wait_for_picker(app, pilot):
        for _ in range(200):
            await pilot.pause(0.05)
            if (isinstance(app.screen, ModelsScreen)
                    and any(entry.get("value") == "chatgpt|fixture-chat-model"
                            for entry in app.screen.entries)):
                return app.screen
        raise AssertionError(("ChatGPT account model picker did not load",
                              catalog_calls, getattr(app, "_account_models_attempted", set()),
                              getattr(app, "_account_model_status", "")))

    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.click("#model-button")
        assert isinstance(app.screen, ModelsScreen)
        screen = await wait_for_picker(app, pilot)
        assert screen.provider_scope == "chatgpt"
        assert any(entry.get("value") == "chatgpt|fixture-chat-model"
                   for entry in screen.entries), {
                       "calls": catalog_calls, "status": app._account_model_status,
                       "rows": [(entry["kind"], entry["value"])
                                for entry in screen.entries],
                   }
        assert selected_provider_name() == "chatgpt"
        assert resolved_chat_model("chatgpt") == "auto"

        choice = next(button for button in screen.query(".model-choice")
                      if screen.choices[button.id].get("value") == "chatgpt|fixture-chat-model")
        choice.focus()
        await pilot.press("enter")
        for _ in range(100):
            await pilot.pause(0.02)
            if resolved_chat_model("chatgpt") == "fixture-chat-model":
                break
        assert resolved_chat_model("chatgpt") == "fixture-chat-model"


@pytest.mark.asyncio
async def test_model_button_label_falls_back_without_provider(monkeypatch):
    from isycode import tui_app_providers as providers_mixin
    monkeypatch.setattr(providers_mixin, "selected_provider_name",
                        lambda: (_ for _ in ()).throw(providers_mixin.ConfigurationError("nope")))
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        assert app._model_button_label() == "Model ▾"


@pytest.mark.asyncio
async def test_model_button_label_uses_wider_budget_on_wide_terminal(monkeypatch):
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    monkeypatch.setenv("ISYCODE_MODEL", "stepfun-ai/step-5-preview")
    app = TUIApp()
    async with app.run_test(size=(140, 30)) as pilot:
        await pilot.pause()
        label = app._model_button_label()
        assert "Step 5" in label and label.endswith("▾")
        assert len(label) > 12
