"""Interactive chat with TUI (ISYCO branding)."""

from __future__ import annotations
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Input, RichLog, Static, Button, Label, TextArea
from textual.reactive import reactive
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual import events
from rich.text import Text

from .run import Agent, AgentContext, AVAILABLE_TOOLS, DEFAULT_SYSTEM_PROMPT
from .providers import ProviderRegistry
from .provider_screen import ProviderWizard, ProviderWizardState
from ..policy import PolicyEngine
from ..runtime import RuntimeRegistry
from ..secret_broker import SecretBroker
from ..resident import ResidentRecorder
from ..resident import SelfScanner
from ..resident import ResidentReader
from ..mode import ModeController
from ..plan import PlanStore
from ..todo import TodoStore
from ..file_icons import ascii_file_label


WELCOME_MSG = (
    "[bold cyan]ISYCODE[/bold cyan] IDE · terminal — el modelo propone; el host decide y ejecuta.\n"
    "\n"
    "Commands: /provider  /model  /plan  /code  /scan  /policy  /sessions  /clear  /help  /exit\n"
    "Keys: Ctrl+P provider - Ctrl+O options - Ctrl+T todos - Shift+Tab mode - Ctrl+S sidebar\n"
)


APP_COMMANDS = (
    ("/provider", "Select or add provider"),
    ("/model", "Switch model"),
    ("/plan", "PLAN mode"),
    ("/code", "CODER mode"),
    ("/clear", "Clear conversation"),
    ("/session", "Show session info"),
    ("/sessions", "Reopen a saved conversation"),
    ("/resume", "Resume by saved conversation ID"),
    ("/scan", "Refresh resident map"),
    ("/policy", "Show policy rules"),
    ("/help", "Show app commands"),
    ("/exit", "Exit ISyCode"),
)


def _parse_tool_chunk(chunk: str):
    """The agent emits a leading newline before its tool-result marker."""
    text = chunk.lstrip("\r\n")
    if not text.startswith(("✅", "❌")):
        return None
    try:
        name, result = text[1:].split(":", 1)
        return name.strip(), result.strip(), text.startswith("✅")
    except ValueError:
        return "tool", text, text.startswith("✅")


class ChatLog(RichLog):
    """Chat log with compact labeled messages and auto-scroll."""

    def __init__(self, **kwargs):
        super().__init__(wrap=True, highlight=True, markup=True, **kwargs)

    def add_user(self, text: str):
        self.write(f"[dim green]YOU[/dim green]\n{text}\n")

    def add_assistant(self, text: str):
        self.write(f"[dim cyan]ASSISTANT[/dim cyan]\n{text}\n")

    def add_tool(self, name: str, result: str, success: bool):
        style = "green" if success else "red"
        self.write(Text(f"[OK] [TOOL] {name}\n{result}\n" if success else f"[ERR] [TOOL] {name}\n{result}\n", style=style))

    def add_system(self, text: str):
        self.write(f"[dim yellow]SYSTEM[/dim yellow]\n{text}\n")


class PromptSubmitted(Message):
    """Posted by the input area when the user submits a prompt."""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class CommandQueryChanged(Message):
    """Posted by the input when its slash-command query changes."""

    def __init__(self, query: str) -> None:
        self.query = query
        super().__init__()


class CommandPalette(Static):
    """Small app-command palette rendered directly above the input."""

    query = reactive("")
    selected = reactive(0)

    def filtered(self) -> list[tuple[str, str]]:
        query = self.query.lower().strip()
        if not query.startswith("/"):
            return []
        return [item for item in APP_COMMANDS if query in item[0]]

    def render(self) -> Text:
        matches = self.filtered()
        if not matches:
            return Text("No matching app commands", style="dim")
        self.selected = min(self.selected, len(matches) - 1)
        text = Text()
        for index, (command, description) in enumerate(matches[:7]):
            marker = "▸ " if index == self.selected else "  "
            text.append(marker + command.ljust(14), "bold cyan" if index == self.selected else "cyan")
            text.append(description + "\n", "bold" if index == self.selected else "dim")
        return text

    def set_query(self, query: str) -> None:
        self.query = query
        self.selected = 0
        self.set_class(not self.filtered(), "empty")
        self.set_class(not query.startswith("/"), "hidden")

    def move(self, delta: int) -> None:
        matches = self.filtered()
        if matches:
            self.selected = (self.selected + delta) % len(matches)
            self.refresh()

    def selected_command(self) -> str | None:
        matches = self.filtered()
        return matches[self.selected][0] if matches else None


class InputArea(TextArea):
    """Multiline input: Enter sends, Shift+Enter newline, Ctrl+Up/Down history."""

    BINDINGS = [
        Binding("enter", "submit_input", "Send", priority=True),
        Binding("shift+enter", "insert_newline", "Newline", priority=True),
        Binding("ctrl+j", "submit_input", "Send", priority=True),
        Binding("ctrl+up", "history_up", "History up", priority=True),
        Binding("ctrl+down", "history_down", "History down", priority=True),
    ]

    def __init__(self, **kwargs):
        super().__init__(
            text="",
            soft_wrap=True,
            show_line_numbers=False,
            placeholder="Type a request — Enter sends, Shift+Enter newline",
            **kwargs,
        )
        self.prompt_history: list[str] = []
        self.history_index = -1

    def action_insert_newline(self) -> None:
        self.insert("\n")

    def action_submit_input(self) -> None:
        text = self.text.strip()
        if not text:
            return
        palette = getattr(self.app, "command_palette", None)
        if palette is not None and palette.has_class("active") and text.startswith("/"):
            command = palette.selected_command()
            self.text = ""
            if command:
                self.app.accept_command(command)
            return
        self.add_to_history(text)
        self.text = ""
        self.post_message(PromptSubmitted(text))

    def action_history_up(self) -> None:
        if not self.prompt_history:
            return
        if self.history_index < len(self.prompt_history) - 1:
            self.history_index += 1
            self.text = self.prompt_history[-(self.history_index + 1)]

    def action_history_down(self) -> None:
        if self.history_index > 0:
            self.history_index -= 1
            self.text = self.prompt_history[-(self.history_index + 1)]
        elif self.history_index == 0:
            self.history_index = -1
            self.text = ""

    def add_to_history(self, text: str) -> None:
        if text.strip() and (not self.prompt_history or self.prompt_history[-1] != text):
            self.prompt_history.append(text)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.post_message(CommandQueryChanged(self.text))

    async def on_key(self, event: events.Key) -> None:
        app = self.app
        palette = getattr(app, "command_palette", None)
        if palette is not None and palette.has_class("active"):
            if event.key == "up":
                palette.move(-1)
                event.stop()
            elif event.key == "down":
                palette.move(1)
                event.stop()
            elif event.key == "escape":
                self.text = ""
                event.stop()
            elif event.key == "enter":
                command = palette.selected_command()
                if command:
                    self.text = ""
                    app.accept_command(command)
                event.stop()


class StatusBar(Static):
    """Compact bottom status strip: provider / mode / resident / runtime / turn."""

    provider = reactive("openai")
    model = reactive("gpt-4o")
    provider_key = reactive("not configured")
    runtime = reactive("layer_a")
    turns = reactive(0)
    mode = reactive("plan")
    resident = reactive("LOCAL")
    busy = reactive(False)
    compact = reactive(False)

    def render(self) -> Text:
        t = Text()
        if not self.compact:
            t.append("  │  ", "dim")
            t.append("/ commands  Ctrl+P provider  Ctrl+T todo  Ctrl+S sidebar", "dim")
        t.append("  ", "")
        t.append(f"[{self.mode.upper()}]", "bold green" if self.mode == "coder" else "bold yellow")
        t.append("  │  ", "dim")
        t.append(f"{self.provider}", "bold cyan")
        t.append(" / ", "dim")
        t.append(f"{self.model}", "cyan")
        t.append("  │  ", "dim")
        t.append(f"{self.runtime}", "bold yellow")
        t.append("  │  ", "dim")
        t.append(f"RESIDENT {self.resident}", "dim")
        t.append("  │  ", "dim")
        t.append(f"Turn {self.turns}", "bold")
        if self.busy:
            t.append("  │  ", "dim")
            t.append("▸ running…", "bold green")
        t.append("  ", "")
        return t


class SidebarPanel(Static):
    """Agent cockpit: MODE / TODO / RESIDENT / RUNTIME / SESSION / HELP."""

    mode = reactive("plan")
    provider = reactive("openai")
    model = reactive("gpt-4o")
    runtime = reactive("layer_a")
    turns = reactive(0)
    policy = reactive("active")
    workspace = reactive("")
    resident_active = reactive(False)
    resident_components = reactive(0)
    resident_scan = reactive("never")
    todos = reactive([])
    busy = reactive(False)

    def render(self) -> Text:
        t = Text()
        t.append("MODE\n", "bold")
        t.append(f"[{self.mode.upper()}]", "bold green" if self.mode == "coder" else "bold yellow")
        t.append("  write " + ("enabled" if self.mode == "coder" else "plan-only"), "dim")
        t.append("\n\n")

        t.append("TODO", "bold")
        counts = self._todo_counts()
        if counts:
            t.append(f"   {counts}", "dim")
        t.append("\n")
        items = self.todos[:5]
        if items:
            for item in items:
                status = item.get("status", "open")
                if status == "done":
                    mark, style = "[✓]", "dim"
                elif status == "in_progress":
                    mark, style = "[~]", "bold yellow"
                else:
                    mark, style = "[ ]", None
                t.append(f"{mark} {item.get('text', '')}\n", style)
            if len(self.todos) > 5:
                t.append(f"  +{len(self.todos) - 5} more\n", "dim")
        else:
            t.append("No pending tasks\n", "dim")
        t.append("\n")

        t.append("PROVIDER\n", "bold")
        t.append(f"{self.provider}\n", "bold cyan")
        t.append(f"model: {self.model}\n", "dim")
        t.append(f"API key: {self.provider_key}\n", "dim")
        t.append("Ctrl+P change / add\n", "dim")
        t.append("\n")

        t.append("RESIDENT\n", "bold")
        if self.resident_active:
            t.append("● active", "bold green")
        else:
            t.append("○ idle", "dim")
        t.append("\n")
        t.append(f"map: {self.resident_components} components\n", None)
        t.append(f"last scan: {self.resident_scan}\n", "dim")
        t.append("\n")

        t.append("RUNTIME\n", "bold")
        t.append(f"layer: {self.runtime}\n", None)
        t.append(f"policy: {self.policy}\n", "dim")
        t.append(ascii_file_label(self.workspace, is_dir=True) + "\n", "dim")
        t.append("\n")

        t.append("SESSION\n", "bold")
        t.append(f"turn: {self.turns}\n", None)
        t.append(f"{self.provider} / {self.model}\n", "dim")
        if self.busy:
            t.append("▸ agent running…\n", "bold green")
        t.append("\n")

        t.append("HELP\n", "bold")
        for line in (
            "Ctrl+P provider   Ctrl+O options",
            "Shift+Tab mode    Ctrl+T todos",
            "Ctrl+J send       Ctrl+S sidebar",
        ):
            t.append(f"{line}\n", "dim")
        return t

    def _todo_counts(self) -> str:
        open_count = sum(1 for item in self.todos if item.get("status") != "done")
        done_count = len(self.todos) - open_count
        parts = []
        if open_count:
            parts.append(f"{open_count} open")
        if done_count:
            parts.append(f"{done_count} done")
        return " - ".join(parts)


class ChangeApprovalModal(ModalScreen[bool | str]):
    """Review the frozen host proposal, with explicit approve/reject choices."""

    CSS = """
    ChangeApprovalModal { align: center middle; }
    #change-review { width: 90%; height: 85%; padding: 1 2; background: $surface; border: thick $accent; }
    #change-review TextArea { height: 1fr; }
    #change-review Horizontal { height: 3; }
    #change-review Button { width: 1fr; }
    """
    BINDINGS = [Binding("escape", "reject_change", "Rechazar", priority=True)]

    def __init__(self, call):
        super().__init__()
        self.call = call

    def compose(self) -> ComposeResult:
        with Vertical(id="change-review"):
            yield Label(Text("[CMD] Comando" if getattr(self.call, "approval_kind", "") == "command" else ascii_file_label(self.call.arguments.get("path", ""))))
            yield Label(Text(f"Base SHA-256: {getattr(self.call, 'before_sha256', None) or 'ver detalle'}"))
            yield TextArea(self.call.prepared_diff, read_only=True, show_line_numbers=True)
            with Horizontal():
                yield Button("Rechazar", id="reject-change", variant="error")
                yield Button("Aprobar una vez", id="approve-change", variant="success")
                if getattr(self.call, "approval_kind", "") == "command":
                    yield Button("Permitir siempre este comando", id="always-command", variant="primary")

    def on_mount(self):
        self.query_one("#reject-change", Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.dismiss("always" if event.button.id == "always-command" else event.button.id == "approve-change")

    def action_reject_change(self):
        self.dismiss(False)


class OptionsModal(ModalScreen):
    """Small command palette for common host actions."""

    CSS = """
    OptionsModal { align: center middle; }
    #options-box { width: 44; height: auto; max-height: 90%; overflow-y: auto; padding: 0 2; background: $surface; border: thick $primary; }
    #options-title { text-style: bold; content-align: center top; margin: 0; }
    #options-box Button { width: 1fr; height: 1; min-height: 1; min-width: 12; padding: 0 1; border: none; background: $surface; color: $primary; margin: 0; }
    """

    def compose(self) -> ComposeResult:
        yield Container(
            Label("ISYCODE OPTIONS", id="options-title"),
            Button("PLAN mode", id="option-plan"),
            Button("CODER mode", id="option-coder"),
            Button("Provider / API key", id="option-provider"),
            Button("Resident self-scan", id="option-scan"),
            Button("Show policy", id="option-policy"),
            Button("Clear chat", id="option-clear"),
            Button("Close", id="option-close"),
            id="options-box",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id.removeprefix("option-")
        if action == "close":
            self.dismiss(None)
        else:
            self.dismiss(action)


class ConversationsModal(ModalScreen):
    CSS = """
    ConversationsModal { align: center middle; }
    #conversations-box { width: 85%; height: 80%; padding: 1 2; background: $surface; border: thick $accent; }
    #saved-conversations { height: 1fr; }
    #saved-conversations Button { width: 1fr; height: auto; margin-bottom: 1; }
    """
    BINDINGS = [Binding("escape", "dismiss", "Cerrar", priority=True)]

    def __init__(self, sessions):
        super().__init__()
        self.sessions = sessions

    def compose(self):
        with Vertical(id="conversations-box"):
            yield Label("Conversaciones guardadas · Esc cierra")
            with VerticalScroll(id="saved-conversations"):
                if not self.sessions:
                    yield Label("Todavía no hay conversaciones en este proyecto.")
                for session in self.sessions:
                    yield Button(Text(session["title"] + " · " + session["updated"][:16]), id="saved-" + session["id"])

    def on_button_pressed(self, event):
        event.stop()
        self.dismiss(event.button.id.removeprefix("saved-"))


class TodoModal(ModalScreen):
    """Persistent TODO list without requiring slash commands."""

    CSS = """
    TodoModal { align: center middle; }
    #todo-box { width: 64; height: auto; max-height: 90%; overflow-y: auto; padding: 0 2; background: $surface; border: thick $primary; }
    #todo-input { margin: 1 0; }
    #todo-list { height: auto; max-height: 18; margin: 0; }
    #todo-list Button { width: 1fr; height: 1; min-height: 1; margin: 0 0 1 0; }
    #todo-actions { height: 3; }
    """

    def __init__(self, store: TodoStore):
        super().__init__()
        self.store = store

    def compose(self) -> ComposeResult:
        yield Container(
            Label("TODO LIST", id="todo-title"),
            Input(placeholder="Add a task...", id="todo-input"),
            Vertical(id="todo-list"),
            Horizontal(
                Button("Add", id="todo-add", variant="primary"),
                Button("Close", id="todo-close"),
                id="todo-actions",
            ),
            id="todo-box",
        )

    async def on_mount(self) -> None:
        await self.refresh_items()
        self.query_one("#todo-input", Input).focus()

    async def refresh_items(self) -> None:
        listing = self.query_one("#todo-list", Vertical)
        await listing.remove_children()
        for item in self.store.list():
            mark = "[x]" if item.get("status") == "done" else "[ ]"
            item_id = item["id"].replace(":", "_")
            await listing.mount(Button(f"{mark} {item['text']}", id=f"todo-toggle-{item_id}"))

    async def add_item(self) -> None:
        input_box = self.query_one("#todo-input", Input)
        if input_box.value.strip():
            self.store.add(input_box.value)
            input_box.value = ""
            await self.refresh_items()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "todo-input":
            asyncio.create_task(self.add_item())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "todo-add":
            asyncio.create_task(self.add_item())
        elif button_id == "todo-close":
            self.dismiss(None)
        elif button_id.startswith("todo-toggle-"):
            item_id = button_id.removeprefix("todo-toggle-").replace("_", ":")
            self.store.toggle(item_id)
            asyncio.create_task(self.refresh_items())


class IsycoAgentApp(App):
    """ISYCO Agent TUI — agent cockpit: conversation + state panel + status strip."""

    # ISyCode owns Ctrl+P for provider selection; app commands use `/`.
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    #action-bar {
        height: 1;
        layout: horizontal;
        align: right middle;
        padding: 0 2;
        background: $background;
    }
    #action-bar Button {
        height: 1;
        min-height: 1;
        min-width: 12;
        padding: 0 1;
        border: none;
        background: $panel;
        color: $text;
    }
    #action-bar #open-options { color: $accent; }
    #action-bar #open-todo { color: $success; }
    #action-bar #open-provider { color: $accent; }
    #action-bar.mode-plan #open-options { color: $warning; }
    #action-bar.mode-coder #open-options { color: $success; }

    #header-title {
        layout: horizontal;
        align: left middle;
        padding: 0 1;
        color: $text;
        background: $panel;
        height: 1;
        margin: 0;
    }

    #main-area {
        layout: horizontal;
        height: 1fr;
        margin: 0 0 1 0;
    }

    #chat-col {
        layout: vertical;
        width: 1fr;
        height: 1fr;
        background: $surface;
    }

    .command-palette {
        height: auto;
        max-height: 8;
        margin: 0 1;
        padding: 0 1;
        background: $panel;
        border: solid $primary;
    }
    .command-palette.hidden { display: none; }
    .command-palette.empty { color: $text; }

    #sidebar {
        width: 36;
        height: 1fr;
        overflow-y: auto;
        padding: 1 1 1 2;
        background: $panel;
        border-left: solid $primary;
    }

    #sidebar.slim { width: 32; }
    #sidebar.collapsed { display: none; }
    #sidebar.hidden { display: none; }
    #action-bar.hidden { display: none; }
    #sidebar.mode-plan { border-left: solid $warning; }
    #sidebar.mode-coder { border-left: solid $success; }

    .bottom-bar {
        dock: bottom;
        layout: horizontal;
        align: left middle;
        padding: 0 1;
        color: $text;
        background: $panel;
        height: 1;
        margin: 0 0 0 0;
    }

    #chat-col {
        layout: vertical;
        width: 1fr;
        height: 1fr;
        background: $surface;
    }

    #input-area {
        height: 5;
        margin: 0 1 1 1;
        padding: 0 1;
        border: none;
        background: $panel;
    }
    #input-area:focus {
        border: solid $accent;
    }

    #status {
        height: 1;
        background: $panel;
        border: none;
    }
    StatusBar { padding: 0 1; }
    StatusBar.mode-plan { color: $warning; }
    StatusBar.mode-coder { color: $success; }

    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("ctrl+p", "provider_picker", "Provider"),
        Binding("ctrl+a", "provider_wizard", "Connect provider", priority=True),
        Binding("ctrl+o", "open_options", "Options"),
        Binding("ctrl+t", "open_todo", "Todos"),
        Binding("ctrl+s", "toggle_sidebar", "Sidebar"),
        Binding("shift+tab", "toggle_mode", "Toggle PLAN/CODER", priority=True),
    ]

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o",
        working_dir: str = ".",
        max_turns: int = 20
    ):
        super().__init__()
        self.title = "ISYCODE"
        self.sub_title = str(working_dir)
        self.provider_name = provider
        self.model_name = model
        self.working_dir = Path(working_dir)
        self.max_turns = max_turns

        # Core components
        self.secret_broker = SecretBroker()
        self.provider_registry = ProviderRegistry(self.secret_broker)
        self.policy_engine = PolicyEngine()
        self.runtime_registry = RuntimeRegistry(self.working_dir)
        self.mode_controller = ModeController(self.working_dir)
        self.mode = self.mode_controller.current()
        self.resident_recorder = (
            ResidentRecorder(self.working_dir)
            if (self.working_dir / ".iesyroot").exists()
            else None
        )
        self.todo_store = TodoStore(self.working_dir)
        from core.conversations import ConversationStore, ConversationService
        self.conversation_store = ConversationStore(self.working_dir)
        self.conversation_service = ConversationService(self.conversation_store)
        saved = self.conversation_store.list()
        self.conversation_id = saved[0]["id"] if saved else None
        self._provider_replacement_required = False

        self.context = AgentContext(
            provider_name=provider,
            model=model,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            working_dir=str(working_dir),
            max_turns=max_turns,
            mode=self.mode,
            plan_context=PlanStore(self.working_dir).context(),
        )

        self.agent = Agent(
            self.context,
            self.provider_registry,
            self.policy_engine,
            self.runtime_registry,
            self.secret_broker,
            self.resident_recorder,
            on_approval=self._approve_change,
        )

        self.chat_log = ChatLog(id="chat")
        self.input_area = InputArea(id="input-area")
        self.command_palette = CommandPalette(id="command-palette", classes="command-palette hidden")
        self.header_title = Static(id="header-title", classes="header-title")
        self.status_bar = StatusBar(id="status")
        self.sidebar = SidebarPanel(id="sidebar")
        self.running = False
        self._turn_task = None

    async def _approve_change(self, call):
        future = asyncio.get_running_loop().create_future()
        modal = ChangeApprovalModal(call)

        def answer(value):
            if not future.done():
                future.set_result("always" if value == "always" else value is True)

        self.push_screen(modal, answer)
        try:
            return await future
        finally:
            if self.screen is modal:
                modal.dismiss(False)

    def compose(self) -> ComposeResult:
        yield self.header_title
        yield Horizontal(
            Button("OPTIONS", id="open-options"),
            Button("TODO", id="open-todo"),
            Button("PROVIDER", id="open-provider"),
            id="action-bar",
        )
        yield Horizontal(
            Vertical(self.chat_log, self.command_palette, self.input_area, id="chat-col"),
            self.sidebar,
            id="main-area",
        )
        yield self.status_bar
        yield Footer()

    def on_mount(self) -> None:
        self.chat_log.add_system(WELCOME_MSG)
        if self.conversation_id:
            self.resume_conversation(self.conversation_id)
        self.refresh_header()
        self.status_bar.provider = self.provider_name
        self.status_bar.model = self.model_name
        self.status_bar.runtime = "layer_a"
        self.status_bar.mode = self.mode
        self.status_bar.resident = "LOCAL"
        self.sidebar.provider = self.provider_name
        self.sidebar.model = self.model_name
        self.sidebar.provider_key = self.provider_key_status(self.provider_name)
        self.sidebar.runtime = "layer_a"
        self.sidebar.mode = self.mode
        self.sidebar.workspace = Path(self.working_dir).name or str(self.working_dir)
        rules = self.policy_engine.get_rules_summary()
        self.sidebar.policy = f"active - {len(rules)} rules"
        resident = ResidentReader(self.working_dir).status()
        self.sidebar.resident_components = resident.get("components", 0)
        self.sidebar.resident_active = resident.get("components", 0) > 0
        self.sidebar.resident_scan = "startup" if self.sidebar.resident_active else "never"
        self.apply_mode_style()
        self.refresh_todo_summary()
        self.input_area.focus()

    def refresh_header(self) -> None:
        self.header_title.update(
            f"ISYCODE   [{self.mode.upper()}]   {self.provider_name} / {self.model_name}   {self.working_dir.name}"
        )

    def provider_key_status(self, name: str) -> str:
        providers = self.provider_registry.list()
        if name not in providers:
            return "not configured"
        if providers[name].get("provider") == "ollama":
            return "local"
        if providers[name].get("auth") == "subscription":
            return "subscription · verify in Providers"
        return "********" if self.provider_registry.has_key(name) else "missing"

    def on_resize(self, event: events.Resize) -> None:
        """Responsive layout: shrink, then hide the sidebar on narrow terminals."""
        width = event.size.width
        self.sidebar.set_class(100 <= width < 116, "slim")
        self.sidebar.set_class(width < 100, "hidden")
        self.query_one("#action-bar").set_class(width < 64, "hidden")
        self.status_bar.compact = width < 116

    def on_prompt_submitted(self, event: PromptSubmitted) -> None:
        text = event.text.strip()
        if not text:
            return
        if self.running:
            self.chat_log.add_system("Agent is busy — wait for the current turn to finish.")
            return
        if text.startswith("/"):
            asyncio.create_task(self.handle_command(text))
        else:
            asyncio.create_task(self.run_agent(text))

    def on_command_query_changed(self, event: CommandQueryChanged) -> None:
        self.command_palette.set_query(event.query)
        self.command_palette.set_class(bool(event.query.startswith("/")), "active")

    def accept_command(self, command: str) -> None:
        self.command_palette.set_query("")
        self.command_palette.set_class(False, "active")
        asyncio.create_task(self.handle_command(command))

    async def handle_command(self, cmd: str) -> None:
        parts = cmd[1:].split()
        command = parts[0].lower()

        if command == "help":
            self.chat_log.add_system("""
[bold]Commands:[/bold]
  /help           - Show this help
  /provider <name> - Switch provider (openai, anthropic, google, ollama)
  /model <name>   - Switch model
  /plan           - Switch to PLAN mode (no writes)
  /code           - Switch to CODER mode
  /scan           - Update the structural resident self-map
  /policy         - Show policy rules
  /clear          - Clear conversation
  /exit           - Exit

[bold]Keys:[/bold]
  Ctrl+P provider - Ctrl+O options - Ctrl+T todos
  Shift+Tab mode - Ctrl+J send - Ctrl+S sidebar
            """)
        elif command == "provider":
            await self.show_provider_picker()
        elif command == "model":
            if len(parts) > 1:
                await self.switch_model(" ".join(parts[1:]))
            else:
                await self.show_model_picker()
        elif command == "policy":
            self.show_policy()
        elif command == "session":
            self.chat_log.add_system(
                f"Session: turn {self.status_bar.turns} · {self.provider_name} / {self.model_name} · mode {self.mode}"
            )
        elif command in ("plan", "code"):
            self.set_mode(command)
        elif command == "scan":
            result = SelfScanner(self.working_dir).scan()
            self._update_resident(result)
            self.chat_log.add_system(f"Resident self-scan: {result.get('summary', result)}")
        elif command == "clear":
            self.action_clear()
        elif command == "sessions":
            if not self.running:
                self.push_screen(ConversationsModal(self.conversation_store.list()), self.resume_conversation)
        elif command == "resume":
            if len(parts) == 2:
                self.resume_conversation(parts[1])
            else:
                self.chat_log.add_system("Usa /sessions o /resume <ID de conversación>.")
        elif command in ("exit", "quit"):
            self.exit()
        else:
            self.chat_log.add_system(f"Unknown command: {command}. Type /help")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-options":
            self.push_screen(OptionsModal(), self.handle_option)
        elif event.button.id == "open-todo":
            self.push_screen(TodoModal(self.todo_store), self.refresh_todo_summary)
        elif event.button.id == "open-provider":
            asyncio.create_task(self.show_provider_picker())

    def refresh_todo_summary(self, result=None) -> None:
        if hasattr(self, "sidebar"):
            self.sidebar.todos = self.todo_store.list()

    def _update_resident(self, result: dict) -> None:
        self.sidebar.resident_active = True
        self.sidebar.resident_components = result.get("components", 0)
        self.sidebar.resident_scan = datetime.now().strftime("%H:%M")

    def handle_option(self, action: str | None) -> None:
        if action == "plan" or action == "coder":
            self.set_mode(action)
        elif action == "scan":
            result = SelfScanner(self.working_dir).scan()
            self._update_resident(result)
            self.chat_log.add_system(f"Resident self-scan: {result.get('summary', result)}")
        elif action == "provider":
            asyncio.create_task(self.show_provider_picker())
        elif action == "policy":
            self.show_policy()
        elif action == "clear":
            self.action_clear()
        elif action == "exit":
            self.exit()

    async def show_provider_picker(self) -> None:
        """Open the single provider connection wizard."""
        self.push_screen(
            ProviderWizard(self.provider_registry, self.secret_broker),
            self._provider_wizard_done,
        )

    def _provider_wizard_done(self, result) -> None:
        if not result:
            return
        name = result["name"]
        provider_type = result["provider"]
        model = result["model"]
        if name not in self.provider_registry.list():
            self.provider_registry.add(name, provider_type, model)
        else:
            config = self.provider_registry.list()[name]
            if config.get("model") != model:
                self.provider_registry.add(name, config["provider"], model, **{key: value for key, value in config.items() if key not in {"provider", "model"}})
        asyncio.create_task(self.switch_provider(name))

    async def show_model_picker(self) -> None:
        providers = self.provider_registry.list()
        config = providers.get(self.provider_name)
        if not config:
            self.chat_log.add_system("No provider configured. Opening provider wizard.")
            await self.show_provider_picker()
            return
        self.push_screen(
            ProviderWizard(
                self.provider_registry,
                self.secret_broker,
                initial_provider=self.provider_name,
                start_state=ProviderWizardState.SELECT_MODEL,
            ),
            self._model_wizard_done,
        )

    def _model_wizard_done(self, result) -> None:
        if result and result.get("model"):
            asyncio.create_task(self.switch_model(result["model"]))

    async def switch_provider(self, name: str) -> None:
        if self.running:
            self.chat_log.add_system("Espera a que termine el turno antes de cambiar de provider.")
            return
        providers = self.provider_registry.list()
        if name not in providers:
            self.chat_log.add_system(f"Provider '{name}' not configured. Use /provider to add it.")
            return

        needs_key = providers[name].get("auth", "none" if providers[name]["provider"] == "ollama" else "api_key") == "api_key"
        if needs_key and not self.provider_registry.has_key(name):
            self.chat_log.add_system(
                f"No API key for '{name}'. Set it with: isyvm secret set {name}"
            )
            return

        self.provider_name = name
        self._provider_replacement_required = False
        self.context.provider_name = name
        self.context.provider_config = None
        self.agent.provider = None  # Force provider reload
        self.status_bar.provider = name
        self.sidebar.provider = name
        self.sidebar.provider_key = self.provider_key_status(name)
        self.status_bar.model = self.provider_registry.list()[name]["model"]
        self.model_name = providers[name]["model"]
        self.context.model = self.model_name
        self.sidebar.model = self.model_name
        self.refresh_header()
        self.chat_log.add_system(f"Switched to provider: {name} ({providers[name]['model']})")

    async def switch_model(self, model: str) -> None:
        if self.running:
            self.chat_log.add_system("Espera a que termine el turno antes de cambiar de modelo.")
            return
        self.model_name = model
        self.context.model = model
        self.context.provider_config = None
        self.status_bar.model = model
        self.sidebar.model = model
        self.refresh_header()
        self.chat_log.add_system(f"Switched to model: {model}")

    def show_policy(self) -> None:
        rules = self.policy_engine.get_rules_summary()
        text = "[bold]Policy Rules:[/bold]\n"
        for i, r in enumerate(rules):
            text += f"  {i+1}. {r['action']} -> {r['runtime']} ({'ALLOW' if r['allowed'] else 'DENY'}) - {r['reason']}\n"
        self.chat_log.add_system(text)

    def set_mode(self, mode: str) -> None:
        if self.running:
            self.chat_log.add_system("El modo del turno activo se conserva hasta que termine.")
            return
        self.mode = self.mode_controller.set(mode)
        self.context.mode = self.mode
        self.status_bar.mode = self.mode
        self.sidebar.mode = self.mode
        self.refresh_header()
        self.apply_mode_style()
        self.chat_log.add_system(f"Mode changed: [{self.mode.upper()}]")

    def apply_mode_style(self) -> None:
        for widget in (self.status_bar, self.sidebar, self.query_one("#action-bar")):
            widget.remove_class("mode-plan", "mode-coder")
            widget.add_class(f"mode-{self.mode}")

    def action_toggle_mode(self) -> None:
        self.set_mode("coder" if self.mode == "plan" else "plan")

    def action_open_options(self) -> None:
        self.push_screen(OptionsModal(), self.handle_option)

    def action_open_todo(self) -> None:
        self.push_screen(TodoModal(self.todo_store), self.refresh_todo_summary)

    def action_toggle_sidebar(self) -> None:
        self.sidebar.toggle_class("collapsed")

    async def run_agent(self, user_input: str) -> None:
        if self.running:
            return
        if self._provider_replacement_required:
            self.chat_log.add_system("Elige explícitamente un provider y modelo con /provider antes de enviar esta conversación.")
            return

        self.running = True
        self._turn_task = asyncio.current_task()
        self.status_bar.busy = True
        self.sidebar.busy = True
        self.chat_log.add_user(user_input)
        self.status_bar.turns += 1
        self.sidebar.turns = self.status_bar.turns

        try:
            buffer = ""
            if self.conversation_id is None:
                self.conversation_id = self.conversation_store.create()
            self.agent.session_id = self.conversation_id
            self.context.session_id = self.conversation_id
            self.context.provider_config = self.provider_registry.get_config(self.context.provider_name, self.context.model or None)
            async for chunk in self.conversation_service.run_agent(self.agent, user_input):
                if not chunk.strip():
                    continue
                # Tool results come prefixed with ✅/❌
                tool_message = _parse_tool_chunk(chunk)
                if tool_message is not None:
                    if buffer.strip():
                        self.chat_log.add_assistant(buffer)
                        buffer = ""
                    tool_name, result, success = tool_message
                    self.chat_log.add_tool(tool_name, result, success=success)
                else:
                    buffer += chunk
            if buffer.strip():
                self.chat_log.add_assistant(buffer)
        except Exception:
            self.chat_log.add_system("No se pudo completar el turno. Revisa Providers y el estado de esta conversación.")
        finally:
            self.running = False
            self._turn_task = None
            self.status_bar.busy = False
            self.sidebar.busy = False
            self.input_area.focus()

    def action_clear(self) -> None:
        if self.running:
            self.chat_log.add_system("Espera a que termine el turno antes de crear otra conversación.")
            return
        self.conversation_id = None
        self._provider_replacement_required = False
        self.agent._session_started = False
        self.context.history = []
        self.chat_log.clear()
        self.chat_log.add_system(WELCOME_MSG)
        self.agent.messages = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]

    def resume_conversation(self, session):
        if not session:
            return
        if self.running:
            self.chat_log.add_system("Espera a que termine el turno antes de cambiar de conversación.")
            return
        if session not in {entry["id"] for entry in self.conversation_store.list()}:
            self.chat_log.add_system("La conversación no existe en este proyecto.")
            return
        self.conversation_id = session
        self.agent._session_started = False
        self.agent.messages = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]
        self.context.history = []
        self.chat_log.clear()
        self.chat_log.add_system(WELCOME_MSG)
        selected = next(entry for entry in self.conversation_store.list() if entry["id"] == session)
        try:
            config = self.provider_registry.get_config(selected["provider"], selected["model"])
            if selected["protocol"] and config.provider_type != selected["protocol"]:
                raise ValueError("El protocolo guardado cambió.")
        except ValueError:
            self._provider_replacement_required = True
            self.provider_name = self.context.provider_name = ""
            self.model_name = self.context.model = ""
            self.chat_log.add_system("El provider/modelo guardado no está disponible. Elige explícitamente un reemplazo con /provider; esta conversación se enviará al provider elegido.")
        else:
            self._provider_replacement_required = False
            self.provider_name = self.context.provider_name = config.name
            self.model_name = self.context.model = config.model
        self.context.provider_config = None
        self.agent.provider = None
        self.status_bar.provider = self.sidebar.provider = self.provider_name
        self.status_bar.model = self.sidebar.model = self.model_name
        self.sidebar.provider_key = self.provider_key_status(self.provider_name) if self.provider_name else "sin seleccionar"
        self.refresh_header()
        for message in self.conversation_store.transcript(session):
            self.chat_log.write(Text(message["role"].upper() + "\n" + message["content"] + "\n"))
        for event in self.conversation_store.events(session):
            if event["kind"] in {"proposal_decided", "command_decided"}:
                self.chat_log.write(Text("DECISIÓN · " + str(event["payload"].get("status", ""))))
        self.chat_log.add_system("Estado del último turno: " + self.conversation_store.turn_status(session))

    def action_quit(self) -> None:
        if self._turn_task is not None:
            self._turn_task.cancel()
        self.exit()

    def action_provider_picker(self) -> None:
        asyncio.create_task(self.show_provider_picker())

    def action_provider_wizard(self) -> None:
        asyncio.create_task(self.show_provider_picker())


def run_chat(
    provider: str = "openai",
    model: str = "gpt-4o",
    working_dir: str = ".",
    max_turns: int = 20
) -> None:
    """Run the interactive chat TUI."""
    app = IsycoAgentApp(provider, model, working_dir, max_turns)
    app.run()
