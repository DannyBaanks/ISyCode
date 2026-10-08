"""Composer, idea box, shell box, and the message queue.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList, Static, TextArea
from rich.text import Text
from isycode.tui_widgets import BoxTitle, ExpandableBox, activate_on_second_click
from isycode.tui_theme import MUTED
from isycode.tui_screens_sessions import PastedTextScreen



class IdeaBox(Static):
    can_focus = True
    BINDINGS = [Binding("enter,space", "expand", "Expand note", show=False)]

    def on_mount(self):
        self.border_title = "Enter / Space / double-click expand"

    def on_click(self, event) -> None:
        self.focus()
        if activate_on_second_click(self, event, "idea"):
            self.action_expand()

    def action_expand(self):
        self.app._open_idea_note()


class ShellBox(IdeaBox):
    def on_click(self, event):
        self.action_expand()

    def action_expand(self):
        self.app._open_shell_box()


class QueuedTitle(BoxTitle):
    BINDINGS = [Binding("space", "toggle_collapsible", "Expand", show=False),
                Binding("enter", "send_queued", "Steer", show=False),
                Binding("escape", "undo_queued", "Undo queue", show=False, priority=True)]

    async def _on_click(self, event):
        if self.app._queued_messages and self.app._selected_queued_message is None:
            self.app._select_queued_message(0)
        await super()._on_click(event)

    def action_send_queued(self):
        self.app._promote_queued_message()

    def action_undo_queued(self):
        self.app._undo_queued_message()


class QueuedBox(ExpandableBox):
    BINDINGS = [Binding("space", "toggle_box", "Expand", show=False),
                Binding("enter", "send_queued", "Steer", show=False),
                Binding("escape", "undo_queued", "Undo queue", show=False, priority=True)]

    def __init__(self, **kwargs):
        super().__init__(OptionList(id="queued-options"), title="Queued", collapsed=True, **kwargs)
        self._title = QueuedTitle(label="Queued", collapsed_symbol="▶", expanded_symbol="▼", collapsed=True)

    def on_click(self, event):
        if self.app._queued_messages and self.app._selected_queued_message is None:
            self.app._select_queued_message(0)
        super().on_click(event)

    def _paint_expand_hint(self):
        self.border_subtitle = Text("Enter: steer · Space: expand · Esc: undo", style=MUTED) if self.has_focus or self.has_focus_within else ""

    def action_send_queued(self):
        self.app._promote_queued_message()

    def action_undo_queued(self):
        self.app._undo_queued_message()


class PromptArea(TextArea):
    """Enter sends or queues; selected queue entries can be promoted explicitly."""

    BINDINGS = [
        Binding("enter", "submit_prompt", "Send", priority=True),
        Binding("up", "slash_up", show=False, priority=True),
        Binding("down", "slash_down", show=False, priority=True),
        Binding("tab", "slash_complete", show=False, priority=True),
        Binding("ctrl+v", "paste_clipboard", "Paste clipboard", show=False, priority=True),
        # ctrl+p belongs to the app-wide command palette (see APP_SHORTCUTS
        # and the composer hint). A focused composer must not shadow it.
        Binding("ctrl+shift+p", "review_pastes", "Review pasted text", show=False, priority=True),
        Binding("ctrl+shift+enter", "capture_idea", "Capture idea", show=False, priority=True),
        Binding("ctrl+a", "select_all", "Select all", show=False, priority=True),
        Binding("shift+enter", "insert_line_break", "New line", show=False, priority=True),
        Binding("ctrl+j", "insert_line_break", "New line", show=False, priority=True),
        Binding("alt+enter", "insert_line_break", "New line", show=False, priority=True),
        Binding("escape", "escape_to_app", "Cancel / back", show=False,
                priority=True),
    ]

    class Submitted(Message):
        def __init__(self, prompt: "PromptArea", value: str) -> None:
            super().__init__()
            self.prompt = prompt
            self.value = value

    async def _on_paste(self, event) -> None:
        if self.read_only:
            return
        from isycode.pasted_text import PastedText
        if not hasattr(self, "pasted_text"):
            self.pasted_text = PastedText()
        label = self.pasted_text.capture(event.text)
        event.stop()
        if result := self._replace_via_keyboard(label, *self.selection):
            self.move_cursor(result.end_location)
            self.focus()

    def action_capture_idea(self):
        store = getattr(self, "pasted_text", None)
        text = store.expand(self.text) if store else self.text
        if text.strip():
            self.app._idea_backlog.append(text)
            self.load_text("")
            self.app.notify(f"Idea captured · {len(self.app._idea_backlog)} pending · /ideas reviews")

    def action_paste_clipboard(self):
        self.app.run_worker(self.app._request_clipboard_paste(self), group="clipboard-user")

    def action_review_pastes(self) -> None:
        store = getattr(self, "pasted_text", None)
        active = [(label, text) for label, text in (store.items.items() if store else ()) if label in self.text]
        import hashlib
        active.extend((label, f"Image · {mime} · {len(data):,} bytes\nSHA-256: {hashlib.sha256(data).hexdigest()}\nSession-local attachment; removing this label prevents its transmission.")
                      for label, (mime, data) in self.app._image_attachments.items.items() if label in self.text)
        if active:
            self.app.push_screen(PastedTextScreen(self, active))
        else:
            self.app.notify("No compacted text in this draft.")

    def action_slash_up(self) -> None:
        app = self.app
        if app._move_slash(-1):
            return
        if self.cursor_location[0] == 0:
            recalled = app._navigate_prompt_history(-1, self.text)
            if recalled is not None:
                self.load_text(recalled)
                self.move_cursor((0, len(self.document.lines[0])))
                return
        self.action_cursor_up()

    def action_slash_down(self) -> None:
        app = self.app
        if app._move_slash(1):
            return
        if self.cursor_location[0] == len(self.document.lines) - 1:
            recalled = app._navigate_prompt_history(1, self.text)
            if recalled is not None:
                self.load_text(recalled)
                self.move_cursor((len(self.document.lines) - 1, len(self.document.lines[-1])))
                return
        self.action_cursor_down()

    def action_slash_complete(self) -> None:
        if not self.app._complete_slash(): self.screen.focus_next()

    def action_submit_prompt(self) -> None:
        if self.app._complete_slash(submit_exact=True):
            return
        self.post_message(self.Submitted(self, self.text))

    def action_insert_line_break(self) -> None:
        self.insert("\n")

    def action_escape_to_app(self) -> None:
        self.app.action_escape_to_chat()


class TasksPanel(Static):
    """The agent's plan; a click folds it to one line or opens it again."""

    can_focus = True
    BINDINGS = [Binding("enter,space", "toggle_tasks", "Expand tasks", show=False)]

    def action_toggle_tasks(self) -> None:
        self.app.action_toggle_tasks()

    def on_click(self) -> None:
        self.focus()
        self.app.action_toggle_tasks()


class BarSpacer(Static):
    """Empty filler in the command bar; never part of a text selection."""

    ALLOW_SELECT = False
