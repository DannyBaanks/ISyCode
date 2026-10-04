"""Session, search, question, and backlog modals.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Button, Input, OptionList, Static
from isycode.chat_sessions import ChatSessionStore
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets.option_list import Option
from rich.text import Text
import time as _time
from typing import cast
from isycode.tui_theme import _fit_cells, CYAN
from isycode.tui_widgets import Collapsible, ChatArea
from isycode.tui_screens_approval import DeleteSessionScreen



class IdeaNoteScreen(ModalScreen):
    """Scrollable live view of the full idea note."""

    CSS = """
    IdeaNoteScreen { align: center middle; background: #000000 58%; }
    #idea-note-card { width: 90; max-width: 95%; height: 75%; padding: 1 2; border: round #514d5a; background: #242529; }
    #idea-note-heading { height: 1; color: #c7b8d4; text-style: bold; }
    #idea-note-scroll { height: 1fr; margin: 1 0; }
    #idea-note-content { height: auto; }
    #idea-note-close { width: 16; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, note: str):
        super().__init__()
        self.note = note

    def compose(self):
        with Vertical(id="idea-note-card"):
            yield Static("Idea box · full note", id="idea-note-heading")
            with VerticalScroll(id="idea-note-scroll"):
                yield Static(Text(self.note), id="idea-note-content")
            yield Button("Close · Esc", id="idea-note-close")

    def action_close(self):
        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "idea-note-close":
            self.dismiss()


class ShellProcessesScreen(ModalScreen):
    """Inspect session-owned sandbox jobs without entering a host shell."""
    CSS = """
    ShellProcessesScreen { align: center middle; background: #000000 60%; }
    #shell-card { width: 90%; height: 85%; border: round #514d5a; padding: 1 2; background: #1e1f22; }
    #shell-processes { height: 8; }
    #shell-output { height: 1fr; scrollbar-size-vertical: 3; }
    #shell-text { height: auto; }
    #shell-actions { height: 3; }
    """
    BINDINGS = [Binding("escape", "close", "Close", show=False)]

    def compose(self):
        with Vertical(id="shell-card"):
            yield Static("ShellBox · sandbox processes · session lifetime")
            yield OptionList(id="shell-processes")
            with ChatArea(id="shell-output"):
                yield Static("Select a process to inspect its output.", id="shell-text", markup=False)
            with Horizontal(id="shell-actions"):
                yield Button("Stop selected", id="shell-stop", variant="warning")
                yield Button("Close", id="shell-close")

    def on_mount(self):
        self._selected_job = None
        self._known_jobs = ()
        self.set_interval(0.5, self.refresh_jobs)
        self.refresh_jobs()

    def refresh_jobs(self):
        jobs = self.app._shell_jobs
        ids = tuple(jobs)
        options = self.query_one("#shell-processes", OptionList)
        if ids != self._known_jobs:
            options.clear_options()
            for job_id in ids:
                options.add_option(Option(job_id, id=job_id))
            self._known_jobs = ids
        for index, job_id in enumerate(ids):
            job = jobs[job_id]
            options.replace_option_prompt_at_index(index, f"{job_id} · {job['status']} · {job['command']}")
        if self._selected_job in jobs:
            job = jobs[self._selected_job]
            self.query_one("#shell-text", Static).update(job["output"] or "No output yet.")
            self.query_one("#shell-stop", Button).disabled = job["task"].done()

    def on_option_list_option_highlighted(self, event):
        if event.option_list.id == "shell-processes":
            self._selected_job = event.option.id
            self.refresh_jobs()

    def on_button_pressed(self, event):
        if event.button.id == "shell-close":
            self.dismiss()
        elif event.button.id == "shell-stop" and self._selected_job:
            job = self.app._shell_jobs[self._selected_job]
            if not job["task"].done():
                job["task"].cancel()
                job["status"] = "stopping"

    def action_close(self):
        self.dismiss()


class PastedTextScreen(ModalScreen):
    """Review exactly what readable paste references will send."""
    CSS = """
    PastedTextScreen { align: center middle; background: #000000 58%; }
    #paste-review-card { width: 90%; height: 80%; border: round #514d5a; padding: 1 2; background: #242529; }
    #paste-review-scroll { height: 1fr; }
    .paste-full-text { height: auto; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, prompt, items):
        super().__init__()
        self.prompt, self.items = prompt, items

    def compose(self):
        with Vertical(id="paste-review-card"):
            yield Static(Text("Attachments · review before sending", style=CYAN))
            with VerticalScroll(id="paste-review-scroll"):
                for index, (label, text) in enumerate(self.items):
                    with Collapsible(title=f"{label} · {len(text)} characters", collapsed=False):
                        yield Static(Text(text), classes="paste-full-text")
                        yield Button("Remove from draft", id=f"paste-remove-{index}")
            yield Button("Close · Esc", id="paste-review-close")

    def action_close(self):
        self.dismiss()

    def on_button_pressed(self, event):
        if event.button.id == "paste-review-close":
            self.dismiss()
        elif event.button.id and event.button.id.startswith("paste-remove-"):
            index = int(event.button.id.rsplit("-", 1)[1])
            label, _ = self.items[index]
            self.prompt.load_text(self.prompt.text.replace(label, ""))
            event.button.disabled = True
            event.button.label = "Removed"


class QueuedMessagesScreen(ModalScreen):
    CSS = """
    QueuedMessagesScreen { align: center middle; background: #000000 58%; }
    #queue-card { width: 90%; height: 75%; padding: 1 2; border: round #514d5a; background: #242529; }
    #queue-scroll { height: 1fr; }
    .queue-message { height: auto; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, app):
        super().__init__()
        self.host = app
        self.messages = list(app._queued_messages)

    def compose(self):
        with Vertical(id="queue-card"):
            yield Static(Text("Message queue · Select queued + empty Send steers · Esc restores draft", style=CYAN))
            with VerticalScroll(id="queue-scroll"):
                if not self.messages:
                    yield Static("No pending messages.")
                for index, text in enumerate(self.messages):
                    with Collapsible(title=f"{index + 1} · " + _fit_cells(" ".join(text.split()), 60), collapsed=True):
                        yield Static(Text(text), classes="queue-message")
                        yield Button("Remove pending message", id=f"queue-remove-{index}")
            yield Button("Close · Esc", id="queue-close")

    def action_close(self):
        self.dismiss()

    def on_button_pressed(self, event):
        if event.button.id == "queue-close":
            self.dismiss()
        elif event.button.id and event.button.id.startswith("queue-remove-"):
            text = self.messages[int(event.button.id.rsplit("-", 1)[1])]
            if text in self.host._queued_messages:
                self.host._queued_messages.remove(text)
                self.host._paint_queued_messages()
            event.button.disabled = True
            event.button.label = "Removed"


class IdeaBacklogScreen(QueuedMessagesScreen):
    def __init__(self, app):
        super().__init__(app)
        self.messages = list(app._idea_backlog)

    def compose(self):
        with Vertical(id="queue-card"):
            yield Static(Text("Idea backlog · captured ideas are not instructions", style=CYAN))
            with VerticalScroll(id="queue-scroll"):
                for index, text in enumerate(self.messages):
                    with Collapsible(title=_fit_cells(" ".join(text.split()), 60), collapsed=True):
                        yield Static(Text(text), classes="queue-message")
                        yield Button("Promote to message queue", id=f"idea-promote-{index}")
                        yield Button("Discard idea", id=f"idea-discard-{index}")
                if not self.messages:
                    yield Static("No captured ideas.")
            yield Button("Close · Esc", id="queue-close")

    def on_button_pressed(self, event):
        button_id = event.button.id or ""
        if button_id == "queue-close":
            self.dismiss()
        elif button_id.startswith(("idea-promote-", "idea-discard-")):
            text = self.messages[int(button_id.rsplit("-", 1)[1])]
            if text not in self.host._idea_backlog:
                return
            if button_id.startswith("idea-promote-"):
                if len(self.host._queued_messages) >= 8:
                    self.host.notify("Message queue is full", severity="warning")
                    return
                self.host._queued_messages.append(text)
                self.host.notify("Idea promoted · queued for the next turn")
            self.host._idea_backlog.remove(text)
            event.button.disabled = True
            event.button.label = "Processed"


class AgentQuestionScreen(ModalScreen[dict]):
    """One selector or text answer. Escape cancels and grants nothing."""

    CSS = """
    AgentQuestionScreen { align: center middle; background: #000000 68%; }
    #agent-question-card { width: 84; max-width: 94%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #ask-question { height: auto; color: #f4f1ea; text-style: bold; margin-bottom: 1; }
    #ask-choices { height: auto; margin-bottom: 1; }
    #ask-choices Button { width: 100%; margin-bottom: 1; }
    #ask-text { margin-bottom: 1; }
    #ask-actions { height: 3; align-horizontal: right; }
    #ask-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel_question", "Cancel", show=False),
                Binding("ctrl+c", "cancel_question", "Cancel", show=False)]

    def __init__(self, question: str, choices: list[str]) -> None:
        super().__init__(id="agent-question")
        self.question = question
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-question-card"):
            yield Static(self.question, id="ask-question", markup=False)
            if self.choices:
                with Vertical(id="ask-choices"):
                    for index, choice in enumerate(self.choices):
                        yield Button(choice, id=f"ask-choice-{index}")
            else:
                yield Input(placeholder="Your answer", id="ask-text", max_length=500)
            with Horizontal(id="ask-actions"):
                yield Button("Cancel", id="ask-cancel")
                if not self.choices:
                    yield Button("Send", id="ask-submit", variant="primary")

    def on_mount(self) -> None:
        if self.choices:
            self.query_one("#ask-choice-0", Button).focus()
        else:
            self.query_one("#ask-text", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id == "ask-cancel":
            self.action_cancel_question()
        elif button_id == "ask-submit":
            self._submit_text()
        elif button_id.startswith("ask-choice-"):
            index = int(button_id.removeprefix("ask-choice-"))
            self.dismiss({"status": "answered", "choice": self.choices[index]})

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ask-text":
            event.stop()
            self._submit_text()

    def _submit_text(self) -> None:
        text = " ".join(self.query_one("#ask-text", Input).value.split())[:500].strip()
        if text:
            self.dismiss({"status": "answered", "text": text})

    def action_cancel_question(self) -> None:
        self.dismiss({"status": "cancelled"})


class BridgePresenceScreen(ModalScreen[bool]):
    """Opt in to one name listing. Cancel is the default."""

    CSS = """
    BridgePresenceScreen { align: center middle; background: #000000 68%; }
    #bridge-presence-card { width: 78; max-width: 94%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #bridge-presence-title { height: auto; color: #f4f1ea; text-style: bold; margin-bottom: 1; }
    #bridge-presence-copy { height: auto; margin-bottom: 1; }
    #bridge-presence-actions { height: 3; align-horizontal: right; }
    #bridge-presence-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "decline", "Cancel", show=False),
                Binding("ctrl+c", "decline", "Cancel", show=False)]

    def __init__(self) -> None:
        super().__init__(id="bridge-presence")

    def compose(self) -> ComposeResult:
        with Vertical(id="bridge-presence-card"):
            yield Static("Read Bridge presence?", id="bridge-presence-title")
            yield Static(
                "This lists recent agent names only. It does not connect, claim a lease, "
                "send a message, or wake anyone. One confirmation, nothing remembered.",
                id="bridge-presence-copy")
            with Horizontal(id="bridge-presence-actions"):
                yield Button("Cancel", id="bridge-presence-no")
                yield Button("Read names", id="bridge-presence-yes", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#bridge-presence-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "bridge-presence-yes")

    def action_decline(self) -> None:
        self.dismiss(False)


class ChatSessionsScreen(ModalScreen[str | None]):
    """Search, resume, rename, fork, and remove saved conversations."""

    CSS = """
    ChatSessionsScreen { align: center middle; background: #000000 58%; }
    #sessions-card { width: 84; max-width: 92%; height: 80%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #sessions-title { height: 2; color: #bb8cff; text-style: bold; }
    #sessions-search { height: 3; margin-bottom: 1; }
    #sessions-list { height: 1fr; margin-bottom: 1; }
    #sessions-actions { height: 5; align-horizontal: center; }
    #sessions-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, session_store: ChatSessionStore) -> None:
        super().__init__()
        self.session_store = session_store
        self.visible_sessions = session_store.list_sessions()

    def compose(self) -> ComposeResult:
        with Vertical(id="sessions-card"):
            yield Static("Conversations", id="sessions-title")
            yield Input(placeholder="Search titles and transcript…", id="sessions-search")
            yield OptionList(*self._options(self.visible_sessions), id="sessions-list")
            with Horizontal(id="sessions-actions"):
                yield Button("New session", id="sessions-new", variant="primary")
                yield Button("Rename", id="sessions-rename")
                yield Button("Fork", id="sessions-fork")
                yield Button("Delete", id="sessions-delete", variant="error")
                yield Button("Close", id="sessions-close")

    @staticmethod
    def _options(sessions) -> list[Option]:
        options = [Option(
            f"{item.title}  ·  {_time.strftime('%b %d %H:%M', _time.localtime(item.updated_at))}",
            id=item.session_id) for item in sessions]
        return options or [Option("No matching conversations", id="empty", disabled=True)]

    def on_mount(self) -> None:
        self.query_one("#sessions-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "sessions-search":
            return
        self.visible_sessions = (self.session_store.search(event.value)
                                 if event.value.strip()
                                 else self.session_store.list_sessions())
        listing = self.query_one("#sessions-list", OptionList)
        listing.clear_options()
        listing.add_options(self._options(self.visible_sessions))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "sessions-search":
            listing = self.query_one("#sessions-list", OptionList)
            if len(self.visible_sessions) == 1:
                self.dismiss(self.visible_sessions[0].session_id)
            else:
                listing.focus()

    def _selected_session_id(self) -> str | None:
        listing = self.query_one("#sessions-list", OptionList)
        index = listing.highlighted
        if index is None or index < 0:
            return None
        option = listing.get_option_at_index(index)
        return str(option.id) if option.id not in {None, "empty"} else None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id not in {None, "empty"}:
            self.dismiss(str(event.option.id))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sessions-new":
            self.dismiss("__new__")
        elif event.button.id == "sessions-close":
            self.dismiss(None)
        elif event.button.id == "sessions-rename":
            session_id = self._selected_session_id()
            if session_id is None:
                return
            try:
                current = self.session_store.load(session_id)
                title = await self.app.push_screen_wait(SessionTitleScreen(current.title))
                if title:
                    self.session_store.rename(session_id, title)
                    self._refresh()
            except (OSError, ValueError):
                return
        elif event.button.id == "sessions-fork":
            session_id = self._selected_session_id()
            if session_id is None:
                return
            try:
                child = self.session_store.fork(session_id)
            except (OSError, ValueError):
                return
            self.dismiss(child.session_id)
        elif event.button.id == "sessions-delete":
            session_id = self._selected_session_id()
            if session_id is None:
                return
            try:
                session = self.session_store.load(session_id)
            except (OSError, ValueError):
                return
            confirmed = await self.app.push_screen_wait(DeleteSessionScreen(session.title))
            if confirmed:
                self.dismiss("__delete__:" + session_id)

    def _refresh(self) -> None:
        query = self.query_one("#sessions-search", Input).value
        self.visible_sessions = (self.session_store.search(query)
                                 if query.strip()
                                 else self.session_store.list_sessions())
        listing = self.query_one("#sessions-list", OptionList)
        listing.clear_options()
        listing.add_options(self._options(self.visible_sessions))


class SessionTitleScreen(ModalScreen[str | None]):
    """Capture a printable session title without touching the transcript."""

    CSS = """
    SessionTitleScreen { align: center middle; background: #000000 58%; }
    #session-title-card { width: 72; max-width: 90%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #session-title-heading { height: 2; color: #bb8cff; text-style: bold; }
    #session-title-input { height: 3; margin-bottom: 1; }
    #session-title-actions { height: 3; align-horizontal: right; }
    #session-title-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.initial_title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="session-title-card"):
            yield Static("Rename conversation", id="session-title-heading")
            yield Input(value=self.initial_title, placeholder="Conversation name", id="session-title-input")
            with Horizontal(id="session-title-actions"):
                yield Button("Cancel", id="session-title-cancel")
                yield Button("Save name", id="session-title-save", variant="primary")

    def on_mount(self) -> None:
        field = self.query_one("#session-title-input", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "session-title-save":
            self.dismiss(self.query_one("#session-title-input", Input).value)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "session-title-input":
            self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ConsoleSearchScreen(ModalScreen[None]):
    """Search the rendered transcript and navigate matching console output."""

    CSS = """
    ConsoleSearchScreen { align: right top; background: #000000 25%; }
    #console-search-card { width: 78; max-width: 94%; height: 12; margin: 1 2; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #console-search-title { height: 1; color: #c7b8d4; text-style: bold; }
    #console-search-input { height: 3; margin-top: 1; }
    #console-search-count { height: 1; color: #aab0c0; }
    #console-search-snippet { height: 2; color: #e0e0e0; }
    #console-search-actions { height: 3; align-horizontal: right; }
    #console-search-actions Button { margin-left: 1; }
    """
    BINDINGS = [
        Binding("escape", "close_search", "Close search"),
        Binding("enter", "next_match", "Next match", show=False),
        Binding("shift+enter", "previous_match", "Previous match", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="console-search-card"):
            yield Static("Find in console", id="console-search-title")
            yield Input(placeholder="Search this conversation…", id="console-search-input")
            yield Static("Type to search the current console", id="console-search-count")
            yield Static("", id="console-search-snippet")
            with Horizontal(id="console-search-actions"):
                yield Button("↑ Previous", id="console-search-previous")
                yield Button("Next ↓", id="console-search-next", variant="primary")
                yield Button("Close", id="console-search-close")

    def on_mount(self) -> None:
        self.query_one("#console-search-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "console-search-input":
            cast(TUIApp, self.app)._search_console(event.value, self)

    def update_results(self, index: int, total: int, snippet: str) -> None:
        if total:
            self.query_one("#console-search-count", Static).update(
                f"{index + 1} / {total} matches  ·  Enter next  ·  Shift+Enter previous")
            self.query_one("#console-search-snippet", Static).update(snippet)
        elif self.query_one("#console-search-input", Input).value:
            self.query_one("#console-search-count", Static).update("No matches")
            self.query_one("#console-search-snippet", Static).update("")
        else:
            self.query_one("#console-search-count", Static).update("Type to search the current console")
            self.query_one("#console-search-snippet", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = cast(TUIApp, self.app)
        if event.button.id == "console-search-next":
            app._move_console_search(1)
        elif event.button.id == "console-search-previous":
            app._move_console_search(-1)
        elif event.button.id == "console-search-close":
            self.action_close_search()

    def action_next_match(self) -> None:
        cast(TUIApp, self.app)._move_console_search(1)

    def action_previous_match(self) -> None:
        cast(TUIApp, self.app)._move_console_search(-1)

    def action_close_search(self) -> None:
        cast(TUIApp, self.app)._clear_console_search()
        self.dismiss(None)
