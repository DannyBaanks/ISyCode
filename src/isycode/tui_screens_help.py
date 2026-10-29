"""Quick Help Overlay (F1 / ?) for ISyCode shell and shortcuts."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from isycode.localization import tr
from isycode.tui_screens_approval import DECISION_CSS


class HelpRow(Horizontal):
    """A two-column shortcut row: key and description."""

    DEFAULT_CSS = """
    HelpRow { height: 1; }
    HelpRow .help-key { width: 26; color: #edf1f5; text-style: bold; }
    HelpRow .help-desc { width: 1fr; color: #a9b5c2; }
    """

    def __init__(self, key: str, description: str) -> None:
        super().__init__()
        self._key = key
        self._desc = description

    def compose(self) -> ComposeResult:
        yield Static(self._key, classes="help-key")
        yield Static(self._desc, classes="help-desc")


class QuickHelpScreen(ModalScreen[None]):
    """Modal cheatsheet grouping all verified ISyCode shortcuts."""

    CSS = DECISION_CSS + """
    QuickHelpScreen { align: center middle; background: #000000 65%; }
    #quick-help-card { width: 96; max-width: 96%; height: auto; max-height: 88%; padding: 1 2; }
    #quick-help-scroll { height: 1fr; max-height: 28; border: none; padding: 0; }
    .help-group-title { color: #38e1ee; text-style: bold; margin-top: 1; margin-bottom: 0; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("f1", "close", "Close"),
        Binding("question_mark", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="quick-help-card", classes="isy-dialog"):
            yield Static(tr("ISyCode · Keyboard Shortcuts & Quick Help"), classes="isy-dialog-title")
            with VerticalScroll(id="quick-help-scroll"):
                # Navigation
                yield Static(tr("Navigation"), classes="help-group-title")
                yield HelpRow("Ctrl+B", tr("Toggle Workspace Rail / sidebar"))
                yield HelpRow("Ctrl+L", tr("Move focus to chat composer"))
                yield HelpRow("Ctrl+P", tr("Open semantic command palette"))
                yield HelpRow("Ctrl+F", tr("Search rendered console output"))
                yield HelpRow("Ctrl+Shift+F", tr("Search session titles and transcripts"))
                yield HelpRow("F6 / Shift+F6", tr("Focus Files / Overview rail"))
                yield HelpRow("F7 / Shift+F7", tr("Widen / narrow workspace rail"))

                # Chat & Reasoning
                yield Static(tr("Chat & Reasoning"), classes="help-group-title")
                yield HelpRow("Enter", tr("Send message / submit prompt"))
                yield HelpRow("Shift+Enter / Ctrl+J", tr("Insert a newline in composer"))
                yield HelpRow("Space", tr("Cycle reasoning (title → preview → full)"))
                yield HelpRow("Alt++ / Alt+-", tr("Increase / decrease reasoning effort"))
                yield HelpRow("Ctrl+T", tr("Fold or expand agent task list"))
                yield HelpRow("Ctrl+Shift+Enter", tr("Capture prompt idea to backlog"))

                # Tools & Clipboard
                yield Static(tr("Tools & Clipboard"), classes="help-group-title")
                yield HelpRow("Ctrl+S", tr("Switch between ShellBox and IdeaBox"))
                yield HelpRow("Ctrl+C", tr("Copy selected text via Workspace Authority"))
                yield HelpRow("Ctrl+A", tr("Select all text in focused block"))
                yield HelpRow(tr("Double-click"), tr("Open copy menu for block / title"))
                yield HelpRow("Ctrl+Shift+P", tr("Review compacted pasted text"))
                yield HelpRow("Escape", tr("Close popup / return to chat"))

            with Horizontal(classes="isy-dialog-actions"):
                yield Button(tr("Close (Esc)"), id="help-close", variant="primary")
            yield Static(tr("Esc / F1 / ? closes · all commands stay behind Workspace Authority"),
                         classes="isy-dialog-hint")

    def on_mount(self) -> None:
        self.query_one("#help-close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
