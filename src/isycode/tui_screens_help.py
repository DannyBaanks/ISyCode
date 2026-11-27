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
    /* A row grows with its description: a long localized sentence wraps onto
       the next line instead of being cropped at the dialog border. */
    HelpRow { height: auto; min-height: 1; }
    HelpRow .help-key { width: 26; color: #edf1f5; text-style: bold; text-wrap: nowrap; }
    HelpRow .help-desc { width: 1fr; color: #a9b5c2; text-wrap: wrap; overflow: hidden hidden; }
    HelpRow.-compact { height: auto; }
    HelpRow.-compact .help-key { width: 18; }
    """

    def __init__(self, key: str, description: str) -> None:
        super().__init__()
        self._key = key
        self._desc = description

    def compose(self) -> ComposeResult:
        yield Static(self._key, classes="help-key")
        yield Static(self._desc, classes="help-desc")


def _cells(value) -> int:
    """Margin cells as an int: Textual resolves them to int, float or Scalar."""
    try:
        return int(round(float(getattr(value, "value", value) or 0)))
    except (TypeError, ValueError):
        return 0


class QuickHelpScreen(ModalScreen[None]):
    """Modal cheatsheet grouping all verified ISyCode shortcuts."""

    CSS = DECISION_CSS + """
    /* Vertical placement is driven from _fit_card (margin-top), because the
       bottom rows of the terminal belong to the composer, not to this modal. */
    QuickHelpScreen { align: center top; background: #000000 70%; }
    /* max-height is refined in _fit_card: the card must end above the composer
       it covers, otherwise its bottom border collides with the prompt frame. */
    #quick-help-card { width: 96; max-width: 96%; height: auto; max-height: 80%; padding: 1 2; }
    #quick-help-scroll { height: 24; border: none; padding: 0; overflow-y: auto; }
    .help-group-title { color: #38e1ee; text-style: bold; margin-top: 1; margin-bottom: 0; text-wrap: nowrap; }
    QuickHelpScreen.-narrow #quick-help-card { width: 100%; max-width: 100%; }
    QuickHelpScreen.-narrow HelpRow .help-key { width: 18; }
    /* The shared dialog title reserves up to three rows; the help title is one
       line in every catalog, so give the rows back to the shortcut list. */
    #quick-help-card .isy-dialog-title { height: 1; max-height: 1; margin-bottom: 0; }
    #quick-help-card .isy-dialog-actions { margin-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("f1", "close", "Close"),
        Binding("question_mark", "close", "Close"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[tuple[HelpRow, str]] = []

    def _row(self, key: str, description: str) -> HelpRow:
        row = HelpRow(key, description)
        self._rows.append((row, key))
        return row

    def compose(self) -> ComposeResult:
        with Vertical(id="quick-help-card", classes="isy-dialog"):
            yield Static(tr("ISyCode · Keyboard Shortcuts & Quick Help"), classes="isy-dialog-title")
            with VerticalScroll(id="quick-help-scroll"):
                # Navigation
                yield Static(tr("Navigation"), classes="help-group-title")
                yield self._row("Ctrl+B", tr("Background the live process / toggle sidebar"))
                yield self._row("Ctrl+L", tr("Move focus to chat composer"))
                yield self._row("Ctrl+P", tr("Open semantic command palette"))
                yield self._row("Ctrl+F", tr("Search rendered console output"))
                yield self._row("Ctrl+Shift+F", tr("Search session titles and transcripts"))
                yield self._row("F6 / Shift+F6", tr("Focus Files / Overview rail"))
                yield self._row("F7 / Shift+F7", tr("Widen / narrow workspace rail"))

                # Chat & Reasoning
                yield Static(tr("Chat & Reasoning"), classes="help-group-title")
                yield self._row("Enter", tr("Send message / submit prompt"))
                yield self._row("Shift+Enter / Ctrl+J", tr("Insert a newline in composer"))
                yield self._row("Space", tr("Cycle reasoning (title → preview → full)"))
                yield self._row("Alt++ / Alt+-", tr("Increase / decrease reasoning effort"))
                yield self._row("Ctrl+T", tr("Fold or expand agent task list"))
                yield self._row("Ctrl+Shift+Enter", tr("Capture prompt idea to backlog"))

                # Tools & Clipboard
                yield Static(tr("Tools & Clipboard"), classes="help-group-title")
                yield self._row("Ctrl+S", tr("Switch between ShellBox and IdeaBox"))
                yield self._row("Ctrl+C", tr("Copy selected text via Workspace Authority"))
                yield self._row("Ctrl+A", tr("Select all text in focused block"))
                yield self._row(tr("Double-click"), tr("Open copy menu for block / title"))
                yield self._row("Ctrl+Shift+P", tr("Review compacted pasted text"))
                yield self._row("Escape", tr("Close popup / return to chat"))

            with Horizontal(classes="isy-dialog-actions"):
                yield Button(tr("Close (Esc)"), id="help-close", variant="primary")
            yield Static(tr("Esc / F1 / ? closes · all commands stay behind Workspace Authority"),
                         classes="isy-dialog-hint")

    def on_mount(self) -> None:
        self._apply_width(self.app.size.width)
        self.query_one("#help-close", Button).focus()

    def on_resize(self, event) -> None:
        self._apply_width(event.size.width)

    def _apply_width(self, width: int) -> None:
        """Narrow terminals shorten the key column so descriptions get the room."""
        narrow = width < 100
        self.set_class(narrow, "-narrow")
        for row, _key in self._rows:
            row.set_class(narrow, "-compact")
        self._fit_card()

    def _fit_card(self) -> None:
        """Keep the card above the composer of the base screen.

        The modal is centered on the whole terminal, but the bottom of that
        terminal belongs to the composer and the command bar. Center the card
        in the rows that are actually free (above the prompt) so its bottom
        border never lands on the prompt frame, and let the inner scroll take
        the overflow instead of cropping a sentence.
        """
        try:
            card = self.query_one("#quick-help-card", Vertical)
            prompt = self.app.screen_stack[0].query_one("#prompt-input")
        except Exception:
            return
        prompt_top = prompt.region.y if prompt.region.height else self.size.height
        budget = max(6, prompt_top - 2)
        # Everything the card shows besides the shortcut list: border, padding,
        # the title, the actions row and the hint. Measured, not guessed, so a
        # localized title that wraps to two rows is accounted for.
        chrome = 2 + 2
        for selector in (".isy-dialog-title", ".isy-dialog-actions", ".isy-dialog-hint"):
            try:
                widget = self.query_one(selector)
            except Exception:
                continue
            box = widget.styles
            margins = _cells(box.margin.top) + _cells(box.margin.bottom)
            chrome += (widget.region.height or widget.size.height) + margins
        scroll = self.query_one("#quick-help-scroll", VerticalScroll)
        # The scroll gets exactly the rows left inside the budget, so the close
        # button and the hint always stay inside the card and the bottom border
        # lands above the prompt frame.
        scroll.styles.height = max(3, budget - chrome)
        card.styles.max_height = budget
        card.styles.margin = (1, 0, 0, 0)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
