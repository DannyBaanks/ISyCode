import asyncio

from textual.widgets import Input

from core.agent.chat import IsycoAgentApp


def test_tui_options_and_todo_buttons(tmp_path):
    asyncio.run(_exercise(tmp_path))


async def _exercise(tmp_path):
    app = IsycoAgentApp(working_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.click("#open-options")
        await pilot.pause()
        await pilot.click("#option-plan")
        assert app.mode == "plan"
        await pilot.pause()
        await pilot.press("shift+tab")
        assert app.mode == "coder"

        await pilot.click("#open-todo")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "TodoModal"
        app.screen.query_one("#todo-input", Input).value = "review resident UI"
        await pilot.click("#todo-add")
        await pilot.pause()
        assert "review resident UI" in app.todo_store.summary()


def test_command_palette_filters_and_opens_provider(tmp_path):
    asyncio.run(_exercise_command_palette(tmp_path))


async def _exercise_command_palette(tmp_path):
    app = IsycoAgentApp(working_dir=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        app.input_area.focus()
        await pilot.press("/", "p", "r", "o")
        await pilot.pause()
        assert app.command_palette.has_class("active")
        assert app.command_palette.filtered() == [("/provider", "Select or add provider")]
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.screen_stack[-1].__class__.__name__ == "ProviderWizard"


def test_provider_add_flow_is_reachable(tmp_path):
    asyncio.run(_exercise_provider_add(tmp_path))


async def _exercise_provider_add(tmp_path):
    app = IsycoAgentApp(working_dir=str(tmp_path))
    app.provider_registry.config_path = tmp_path / "config.yaml"
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause(0.2)
        assert app.screen_stack[-1].__class__.__name__ == "ProviderWizard"
        await pilot.press(*list("ollama"))
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.screen.query_one("#wizard-key", Input).has_class("wizard-hidden")
        await pilot.press(*list("llama3.1"))
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert app.provider_name == "ollama"
        assert app.model_name == "llama3.1"


def test_model_command_opens_model_selector(tmp_path):
    asyncio.run(_exercise_model_selector(tmp_path))


async def _exercise_model_selector(tmp_path):
    app = IsycoAgentApp(working_dir=str(tmp_path))
    app.provider_name = "local"
    app.provider_registry._configs = {
        "local": {"provider": "ollama", "model": "llama3.1", "endpoint": "http://localhost:11434"}
    }
    async with app.run_test() as pilot:
        await pilot.press("/", "m", "o")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.screen_stack[-1].__class__.__name__ == "ProviderWizard"


def test_provider_wizard_key_step_and_masking(tmp_path):
    asyncio.run(_exercise_provider_key(tmp_path))


def test_provider_wizard_rejects_empty_key(tmp_path):
    asyncio.run(_exercise_empty_key(tmp_path))


async def _exercise_empty_key(tmp_path):
    app = IsycoAgentApp(working_dir=str(tmp_path))
    app.provider_registry.config_path = tmp_path / "config.yaml"
    app.secret_broker.has_key = lambda name: False
    async with app.run_test() as pilot:
        await pilot.press("ctrl+a")
        await pilot.pause(0.2)
        await pilot.press(*list("openai"))
        await pilot.press("enter")
        await pilot.pause(0.2)
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.screen.state.value == "error"
        assert "required" in app.screen.error_message.lower()


async def _exercise_provider_key(tmp_path):
    app = IsycoAgentApp(working_dir=str(tmp_path))
    app.provider_registry.config_path = tmp_path / "config.yaml"
    keys = {}

    def fake_set(name, key):
        keys[name] = key

    app.secret_broker.set = fake_set
    app.secret_broker.has_key = lambda name: name in keys
    async with app.run_test() as pilot:
        await pilot.press("ctrl+a")
        await pilot.pause(0.2)
        await pilot.press(*list("openai"))
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.screen.state.value == "enter_api_key"
        key_input = app.screen.query_one("#wizard-key", Input)
        key_input.value = "secret-test-key"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert app.screen.state.value == "select_model"
        assert "secret-test-key" not in app.export_screenshot()
