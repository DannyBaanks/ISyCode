"""One decision frame for every modal in the terminal UI.

The product had 41 ModalScreen subclasses, each re-deciding its own card
width, padding, preview height and action row. The vocabulary existed
(``isy-dialog`` classes) but the structure did not, so the same visual bug had
to be fixed globally from ``push_screen``.

Dialog owns the frame and nothing else: dimmed overlay, one card at one of
three widths, a title, a bounded body, an optional hint and a row of actions.
Subclasses supply text and actions; a screen that needs a list or a form adds
children through ``compose_body``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from isycode.localization import tr


@dataclass(frozen=True)
class DialogAction:
    """One choice in the action row."""

    id: str
    label: str
    variant: str = "default"
    focused: bool = False
    disabled: bool = False


class Dialog(ModalScreen[Any]):
    """Shared frame: overlay, card, title, body, actions.

    Class attributes pick the size and the tone; no subclass writes geometry.
    ``narrow`` fits a confirmation, ``normal`` a short explanation, ``wide`` a
    list or a form. ``approval`` and ``danger`` raise the visual weight so the
    surfaces that ask for consent read louder than the chrome around them.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("enter", "default_action", "Confirm", show=False),
    ]

    dialog_title: ClassVar[str] = ""          # msgid, translated by the frame
    dialog_width: ClassVar[str] = "normal"
    dialog_height: ClassVar[str] = "fit"
    dialog_tone: ClassVar[str] = "plain"
    dialog_actions_vertical: ClassVar[bool] = False
    dialog_cancel_result: ClassVar[Any] = None
    dialog_default_action: ClassVar[str] = ""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.add_class(f"dialog-{self.dialog_width}", f"dialog-{self.dialog_height}",
                       f"dialog-{self.dialog_tone}")
        if self.dialog_actions_vertical:
            self.add_class("dialog-actions-vertical")

    # -- content hooks -------------------------------------------------
    def dialog_heading(self) -> str:
        """Translated heading; subclasses may derive it from their arguments."""
        return tr(self.dialog_title) if self.dialog_title else ""

    def dialog_note(self) -> str:
        """Bounded, scrollable copy shown above the body; already translated."""
        return ""

    def dialog_hint(self) -> str:
        """One-line footnote; the only text allowed under the actions."""
        return ""

    def compose_body(self) -> ComposeResult:
        """Extra widgets between the note and the actions."""
        yield from ()

    def dialog_actions(self) -> tuple[DialogAction, ...]:
        return (DialogAction("dialog-cancel", tr("Cancel"), focused=True),)

    # -- frame ---------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Vertical(classes="isy-dialog-card"):
            heading = self.dialog_heading()
            if heading:
                yield Static(heading, classes="isy-dialog-title")
            note = self.dialog_note()
            if note:
                with VerticalScroll(classes="isy-dialog-note"):
                    yield Static(note, markup=False, classes="isy-dialog-copy")
            with VerticalScroll(classes="isy-dialog-body"):
                yield from self.compose_body()
            hint = self.dialog_hint()
            if hint:
                yield Static(hint, markup=False, classes="isy-dialog-hint")
            actions = self.dialog_actions()
            if actions:
                with Horizontal(classes="isy-dialog-actions"):
                    for action in actions:
                        yield Button(action.label, id=action.id,
                                     variant=action.variant if action.variant in
                                     {"default", "primary", "success", "warning", "error"}
                                     else "default",
                                     disabled=action.disabled)

    def on_mount(self) -> None:
        for action in self.dialog_actions():
            if action.focused:
                self.query_one(f"#{action.id}", Button).focus()
                return
        for action in self.dialog_actions():
            if not action.disabled:
                self.query_one(f"#{action.id}", Button).focus()
                return

    # -- behaviour -----------------------------------------------------
    def dismiss_action(self, action_id: str) -> None:
        """Map a pressed action id to the screen's result."""
        self.dismiss(action_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss_action(event.button.id)

    def action_default_action(self) -> None:
        if self.dialog_default_action:
            self.dismiss_action(self.dialog_default_action)

    def action_cancel(self) -> None:
        self.dismiss(self.dialog_cancel_result)


__all__ = ["Dialog", "DialogAction"]
