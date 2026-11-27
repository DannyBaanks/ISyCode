"""Single-screen provider connection wizard for the ISyCode TUI."""

from __future__ import annotations

import asyncio
import httpx
from enum import Enum

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from .providers import ProviderRegistry
from .providers.registry import DEFAULT_ENDPOINTS, DEFAULT_MODELS, PROVIDER_MAP
from ..secret_broker import SecretBroker


class ProviderWizardState(str, Enum):
    SELECT_PROVIDER = "select_provider"
    ENTER_API_KEY = "enter_api_key"
    SELECT_MODEL = "select_model"
    CONNECTING = "connecting"
    COMPLETE = "complete"
    ERROR = "error"


class ProviderWizard(ModalScreen):
    """Connect a provider in one continuous, stateful modal."""

    BINDINGS = [
        Binding("escape", "wizard_back", "Back", priority=True),
    ]

    CSS = """
    ProviderWizard { align: center middle; }
    #wizard-box {
        width: 62;
        height: auto;
        max-height: 100%;
        padding: 0 2;
        background: $surface;
        border: thick $accent;
    }
    #wizard-title { height: 1; text-style: bold; color: $accent; }
    #wizard-step { height: 1; color: $text-muted; }
    #wizard-search { height: 1; margin: 0; }
    #wizard-list { height: 6; min-height: 2; }
    #wizard-key { height: 1; margin: 0; }
    #wizard-status { height: 2; color: $text-muted; }
    #wizard-error { height: auto; min-height: 2; color: $error; }
    #wizard-actions { height: 1; align-horizontal: right; }
    #wizard-actions Button { min-width: 12; margin-left: 1; }
    .wizard-hidden { display: none; }
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        broker: SecretBroker,
        initial_provider: str | None = None,
        start_state: ProviderWizardState = ProviderWizardState.SELECT_PROVIDER,
    ) -> None:
        super().__init__()
        self.registry = registry
        self.broker = broker
        self.state = start_state
        self.selected_provider = initial_provider
        self.provider_type = ""
        self.selected_model: str | None = None
        self.previous_state = ProviderWizardState.SELECT_PROVIDER
        self.error_message = ""
        self.models: list[tuple[str, str]] = []
        self.model_source = "configured/catalog"
        self.suppress_next_enter = False
        self.updating_options = False

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard-box"):
            yield Label("CONNECT A PROVIDER", id="wizard-title")
            yield Label("Step 1 of 3 - choose provider", id="wizard-step")
            yield Input(placeholder="Search providers...", id="wizard-search")
            yield Select([("Loading...", "__loading__")], id="wizard-list", allow_blank=False, prompt="Choose...")
            yield Input(placeholder="API key (hidden)", password=True, id="wizard-key")
            yield Static("", id="wizard-status")
            yield Static("", id="wizard-error")
            with Horizontal(id="wizard-actions"):
                yield Button("Back", id="wizard-back")
                yield Button("Continue", id="wizard-continue", variant="primary")
                yield Button("Cancel", id="wizard-cancel")

    def on_mount(self) -> None:
        if self.state == ProviderWizardState.SELECT_MODEL and self.selected_provider:
            config = self.registry.list().get(self.selected_provider, {})
            self.provider_type = config.get("provider", self.selected_provider)
            self._load_models()
            return
        self._apply_state()

    def _provider_options(self, query: str = "") -> list[tuple[str, str]]:
        configured = self.registry.list()
        entries: list[tuple[str, str]] = []
        for provider_type in PROVIDER_MAP:
            label = provider_type.upper()
            if provider_type in configured:
                label += "  [configured]"
            entries.append((label, provider_type))
        for name, config in configured.items():
            if name not in PROVIDER_MAP:
                entries.append((f"{name}  [{config.get('provider', 'custom')}]", name))
        query = query.strip().lower()
        return [(label, value) for label, value in entries if not query or query in label.lower()]

    def _model_options(self) -> list[tuple[str, str]]:
        return self.models or [(self.selected_model or "No model configured", self.selected_model or "")]

    def _apply_state(self) -> None:
        search = self.query_one("#wizard-search", Input)
        picker = self.query_one("#wizard-list", Select)
        key_input = self.query_one("#wizard-key", Input)
        status = self.query_one("#wizard-status", Static)
        error = self.query_one("#wizard-error", Static)
        step = self.query_one("#wizard-step", Label)
        continue_button = self.query_one("#wizard-continue", Button)

        for widget in (search, picker, key_input, status, error):
            widget.remove_class("wizard-hidden")
        error.update(self.error_message)

        if self.state == ProviderWizardState.SELECT_PROVIDER:
            step.update("Step 1 of 3 - choose provider")
            search.placeholder = "Search providers..."
            self._set_picker_options(self._provider_options(search.value))
            key_input.add_class("wizard-hidden")
            status.update("Select a provider. Configured providers are reused automatically.")
            continue_button.label = "Continue"
            self.set_focus(search)
        elif self.state == ProviderWizardState.ENTER_API_KEY:
            step.update("Step 2 of 3 - API key")
            search.add_class("wizard-hidden")
            picker.add_class("wizard-hidden")
            if self.broker.has_key(self.selected_provider or ""):
                key_input.add_class("wizard-hidden")
                status.update("API key: saved key detected")
                continue_button.label = "Continue"
            else:
                status.update("API key is stored by SecretBroker and never shown after saving.")
                self.set_focus(key_input)
                continue_button.label = "Save and continue"
        elif self.state == ProviderWizardState.SELECT_MODEL:
            step.update("Step 3 of 3 - select model")
            search.placeholder = "Search models..."
            picker.remove_class("wizard-hidden")
            search.remove_class("wizard-hidden")
            key_input.add_class("wizard-hidden")
            self._set_picker_options(self._model_options())
            status.update(f"Models belong only to this provider. Source: {self.model_source}.")
            continue_button.label = "Save / Use"
            self.set_focus(search)
        elif self.state == ProviderWizardState.ERROR:
            search.add_class("wizard-hidden")
            picker.add_class("wizard-hidden")
            key_input.add_class("wizard-hidden")
            status.update("Provider error")
            continue_button.label = "Retry"
        elif self.state == ProviderWizardState.CONNECTING:
            search.add_class("wizard-hidden")
            picker.add_class("wizard-hidden")
            key_input.add_class("wizard-hidden")
            status.update("Connecting provider...")
            continue_button.add_class("wizard-hidden")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "wizard-search":
            picker = self.query_one("#wizard-list", Select)
            options = self._provider_options(event.value) if self.state == ProviderWizardState.SELECT_PROVIDER else self._filtered_models(event.value)
            self._set_picker_options(options or [("No matches", "__none__")])

    def _set_picker_options(self, options: list[tuple[str, str]]) -> None:
        picker = self.query_one("#wizard-list", Select)
        self.updating_options = True
        try:
            picker.set_options(options)
        finally:
            self.updating_options = False

    def _filtered_models(self, query: str) -> list[tuple[str, str]]:
        query = query.strip().lower()
        return [(label, value) for label, value in self._model_options() if not query or query in label.lower()]

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "wizard-list" or event.value is Select.BLANK:
            return
        if self.updating_options:
            return
        value = str(event.value)
        if value in {"__loading__", "__none__"}:
            return
        if self.state == ProviderWizardState.SELECT_PROVIDER:
            self.selected_provider = value
            self.provider_type = self.registry.list().get(value, {}).get("provider", value)
        elif self.state == ProviderWizardState.SELECT_MODEL:
            self.selected_model = value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "wizard-search":
            options = self._provider_options(event.input.value) if self.state == ProviderWizardState.SELECT_PROVIDER else self._filtered_models(event.input.value)
            if options:
                picker = self.query_one("#wizard-list", Select)
                self._set_picker_options(options)
                picker.value = options[0][1]
                if self.state == ProviderWizardState.SELECT_PROVIDER:
                    self.selected_provider = options[0][1]
                    self._advance_from_provider()
                else:
                    self.selected_model = options[0][1]
                    self._complete()
                self.suppress_next_enter = True
            event.stop()
            return
        if event.input.id == "wizard-key":
            self._save_key_and_continue()
            event.stop()

    def on_key(self, event) -> None:
        if event.key != "enter":
            return
        focused = self.app.focused
        if focused is not None and getattr(focused, "id", None) == "wizard-list":
            if self.state == ProviderWizardState.SELECT_PROVIDER:
                self._advance_from_provider()
            elif self.state == ProviderWizardState.SELECT_MODEL:
                self._complete()
            event.stop()
        elif focused is not None and getattr(focused, "id", None) == "wizard-continue":
            self.action_wizard_next()
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "wizard-cancel":
            self.dismiss(None)
        elif event.button.id == "wizard-back":
            self.action_wizard_back()
        elif event.button.id == "wizard-continue":
            self.action_wizard_next()

    def action_wizard_next(self) -> None:
        if self.suppress_next_enter:
            self.suppress_next_enter = False
            return
        if self.state == ProviderWizardState.SELECT_PROVIDER:
            self._advance_from_provider()
        elif self.state == ProviderWizardState.ENTER_API_KEY:
            self._save_key_and_continue()
        elif self.state == ProviderWizardState.SELECT_MODEL:
            self._complete()
        elif self.state == ProviderWizardState.ERROR:
            self.state = self.previous_state
            self.error_message = ""
            self._apply_state()

    def action_wizard_back(self) -> None:
        if self.state == ProviderWizardState.SELECT_PROVIDER:
            self.dismiss(None)
        elif self.state == ProviderWizardState.ENTER_API_KEY:
            self.state = ProviderWizardState.SELECT_PROVIDER
            self._apply_state()
        elif self.state == ProviderWizardState.SELECT_MODEL:
            if self._needs_key() and not self.broker.has_key(self.selected_provider or ""):
                self.state = ProviderWizardState.ENTER_API_KEY
            else:
                self.state = ProviderWizardState.SELECT_PROVIDER
            self._apply_state()
        elif self.state == ProviderWizardState.ERROR:
            self.state = self.previous_state
            self.error_message = ""
            self._apply_state()

    def _needs_key(self):
        config = self.registry.list().get(self.selected_provider or "", {})
        return config.get("auth", "none" if self.provider_type == "ollama" else "api_key") == "api_key"

    def _advance_from_provider(self) -> None:
        if not self.selected_provider:
            return
        config = self.registry.list().get(self.selected_provider, {})
        self.provider_type = config.get("provider", self.selected_provider)
        if self.provider_type.endswith("-subscription") and not config:
            self.error_message = "Prepara y guarda la conexión en Providers → Suscripciones, o usa isycode-ide accounts y provider add --auth subscription."
            self.previous_state = ProviderWizardState.SELECT_PROVIDER
            self.state = ProviderWizardState.ERROR
            self._apply_state()
            return
        if self._needs_key() and not self.broker.has_key(self.selected_provider):
            self.state = ProviderWizardState.ENTER_API_KEY
            self._apply_state()
        else:
            self._load_models()

    def _save_key_and_continue(self) -> None:
        key = self.query_one("#wizard-key", Input).value.strip()
        if self.broker.has_key(self.selected_provider or ""):
            self._load_models()
            return
        if not key:
            self.error_message = "API key is required"
            self.previous_state = ProviderWizardState.ENTER_API_KEY
            self.state = ProviderWizardState.ERROR
            self._apply_state()
            return
        self.broker.set(self.selected_provider or self.provider_type, key)
        self._load_models()

    def _load_models(self) -> None:
        config = self.registry.list().get(self.selected_provider or "", {})
        current = config.get("model", "")
        default = DEFAULT_MODELS.get(self.provider_type, "")
        values = [model for model in (current, default) if model]
        self.models = [(f"{model}  [configured/catalog]", model) for model in dict.fromkeys(values)]
        self.selected_model = current or default or None
        self.query_one("#wizard-search", Input).value = ""
        self.state = ProviderWizardState.SELECT_MODEL
        self._apply_state()
        asyncio.create_task(self._discover_models())

    async def _discover_models(self) -> None:
        """Discover models only through provider-supported endpoints."""
        config = self.registry.list().get(self.selected_provider or "", {})
        endpoint = config.get("endpoint") or DEFAULT_ENDPOINTS.get(self.provider_type, "")
        if not endpoint or self.provider_type not in {"openai", "nvidia", "ollama"}:
            return
        try:
            headers = {"Content-Type": "application/json"}
            if self.provider_type != "ollama":
                headers = self.broker.inject_into_headers(self.selected_provider or self.provider_type, headers)
            url = f"{endpoint.rstrip('/')}/api/tags" if self.provider_type == "ollama" else f"{endpoint.rstrip('/')}/models"
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
            if self.provider_type == "ollama":
                discovered = [item.get("name") for item in data.get("models", [])]
            else:
                discovered = [item.get("id") for item in data.get("data", [])]
            discovered = [model for model in discovered if model]
            if not discovered:
                return
            self.models = [(f"{model}  [available]", model) for model in discovered]
            self.model_source = "provider discovery"
            if self.state == ProviderWizardState.SELECT_MODEL and self.is_attached:
                self._set_picker_options(self.models)
                self.query_one("#wizard-status", Static).update(
                    "Models returned by the selected provider. Access depends on your account."
                )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                self.error_message = "Invalid API key"
                self.previous_state = ProviderWizardState.SELECT_MODEL
                self.state = ProviderWizardState.ERROR
                if self.is_attached:
                    self._apply_state()
        except (httpx.HTTPError, ValueError):
            # Keep the configured catalog; the provider may be offline.
            return

    def _complete(self) -> None:
        if not self.selected_model:
            self.error_message = "Select a model"
            self.previous_state = ProviderWizardState.SELECT_MODEL
            self.state = ProviderWizardState.ERROR
            self._apply_state()
            return
        self.state = ProviderWizardState.COMPLETE
        self.dismiss({
            "name": self.selected_provider or self.provider_type,
            "provider": self.provider_type,
            "model": self.selected_model,
        })


# Compatibility names for imports outside the app. The app uses ProviderWizard.
ProviderSelectScreen = ProviderWizard
AddProviderScreen = ProviderWizard
ModelSelectScreen = ProviderWizard
