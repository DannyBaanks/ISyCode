"""The GUS conversation window (ADR 0011, ADR 0015)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static

from isycode.catalog import role_color
from isycode.gus_l0 import on_gus_branch
from isycode.gus_session import GusState, GusUnavailable, gus_reply
from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction
from isycode.tui_theme import CYAN, GREEN, MUTED, RED, TEXT, YELLOW

# GUS is the maintainer: it takes the maintainer role's identifying color.
GUS_COLOR = role_color("maintainer") or TEXT
Settings = Callable[[], Awaitable[None]]
Undo = Callable[[], Awaitable[bool]]
PickProvider = Callable[[], Awaitable[str | None]]


class GusProviderPickerScreen(Dialog):
    """Quick provider list launched from GUS's top-right header button."""

    dialog_width = "normal"
    dialog_height = "fill"
    dialog_cancel_result = None
    AUTO_FOCUS = "#gus-providers-search"

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__()
        self._rows = list(rows)
        self._visible_rows = list(rows)

    def dialog_heading(self) -> str:
        return tr("GUS model")

    def dialog_note(self) -> str:
        return "GUS never falls back to the chat model. It needs tool calls and a window of 32k tokens or more."

    def dialog_hint(self) -> str:
        return tr("↑↓ move · Enter open · Esc back · Shift+Tab search")

    def compose_body(self) -> ComposeResult:
        yield Input(placeholder=tr("Filter this list…"), id="gus-providers-search")
        yield OptionList(id="gus-providers-list")

    def dialog_actions(self) -> tuple[DialogAction, ...]:
        return (DialogAction("gus-providers-cancel", tr("Back")),)

    def on_mount(self, event) -> None:
        event.prevent_default()
        self._populate("")
        search = self.query("#gus-providers-search").results(Input)
        field = next(search, None)
        if field is not None:
            field.focus()

    def _populate(self, query: str) -> None:
        needle = query.casefold().strip()
        self._visible_rows = [
            row for row in self._rows
            if not needle or needle in f"{row.get('label', '')} {row.get('key', '')} {row.get('detail', '')}".casefold()
        ]
        lst = self.query_one("#gus-providers-list", OptionList)
        lst.clear_options()
        lst.add_options([row["label"] for row in self._visible_rows])
        if self._visible_rows:
            lst.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "gus-providers-search":
            self._populate(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "gus-providers-search":
            event.stop()
            lst = self.query_one("#gus-providers-list", OptionList)
            if self._visible_rows:
                idx = lst.highlighted if lst.highlighted is not None else 0
                if 0 <= idx < len(self._visible_rows):
                    self.dismiss(self._visible_rows[idx]["key"])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "gus-providers-list":
            event.stop()
            idx = event.option_index
            if 0 <= idx < len(self._visible_rows):
                self.dismiss(self._visible_rows[idx]["key"])

    def dismiss_action(self, action_id: str) -> None:
        self.dismiss(None)


class GusScreen(Dialog):
    """Talk to GUS. Its transcript is its own; it never enters the chat history."""

    dialog_width = "wide"
    dialog_height = "fill"
    dialog_cancel_result = None
    # Textual focuses this when the screen activates; without it, a focus asked
    # for during mount can lose to the first focusable widget (the body scroll).
    AUTO_FOCUS = "#gus-input"

    def __init__(self, roots, model_label: str,
                 *, initial: str = "", complete=None, work=None, remember=None,
                 report_text=None, seal=None, generation_text=None,
                 settings: Settings | None = None, undo: Undo | None = None,
                 pick_provider: PickProvider | None = None) -> None:
        super().__init__()
        self.roots = roots
        self.root = roots.visible
        self.target = roots.target
        self.model_label = model_label
        self.initial = initial
        self.complete = complete
        # MK5c: on a gus/* branch a turn uses GUS's tools through ``work``.
        self.work = work
        # ADR 0015: off a gus/* branch GUS may still remember, and only that.
        self.remember = remember
        self.report_text = report_text or (lambda report: "")
        # MK5d: ISyCode runs the gates on GUS's committed work.
        self.seal = seal
        self.generation_text = generation_text or (lambda record: record.get("state", ""))
        self.settings = settings
        self.undo = undo
        self.pick_provider = pick_provider
        self.state = GusState(roots.visible)
        self.busy = False

    def dialog_heading(self) -> str:
        return tr("GUS · {model}", model=self.model_label)

    def dialog_header_actions(self) -> tuple[DialogAction, ...]:
        if self.pick_provider is None:
            return ()
        return (DialogAction("gus-provider", f"{tr('Providers')} ▾"),)

    def dialog_note(self) -> str:
        target = self.target
        return tr("Edits in {target} · reads the machine except credentials · L0 stays human.",
                  target=target if target is not None else tr("no target configured"))

    def dialog_hint(self) -> str:
        return tr("Enter send · Esc close · on a gus/* branch GUS edits its target; elsewhere it reads and answers")

    def compose_body(self) -> ComposeResult:
        with Vertical(id="gus-transcript"):
            for entry in self.state.transcript():
                yield self._line(entry["role"], entry["text"], entry.get("workspace", ""))
        yield Static("", id="gus-status", markup=False)
        yield Input(placeholder=tr("Write to GUS…"), id="gus-input")

    def dialog_actions(self) -> tuple[DialogAction, ...]:
        # Refuse-first (I-03): the harmless action comes first; Clear is never focused.
        actions = [DialogAction("gus-close", tr("Close")),
                   DialogAction("gus-clear", tr("Clear conversation"))]
        if self.settings is not None:
            actions.append(DialogAction("gus-settings", tr("Settings")))
        if self.undo is not None:
            actions.append(DialogAction("gus-undo", tr("Undo this turn")))
        if self.seal is not None:
            actions.append(DialogAction("gus-seal", tr("Run the gates")))
        return tuple(actions)

    def on_mount(self, event) -> None:
        # Dialog would focus its first action; the conversation starts in the input.
        event.prevent_default()
        inputs = self.query("#gus-input").results(Input)
        field = next(inputs, None)
        if field is None:
            return    # closed before it mounted (a quick Esc under load): nothing to focus
        for title in self.query(".isy-dialog-title").results(Static):
            title.styles.color = GUS_COLOR
        field.focus()
        self._scroll_end()
        if self.initial.strip():
            self._submit(self.initial.strip())

    @staticmethod
    def _line(role: str, text: str, workspace: str = "") -> Static:
        speaker = tr("You") if role == "user" else "GUS"
        line = Text(f"{speaker} · ", style=f"bold {GUS_COLOR}" if role != "user" else f"bold {TEXT}")
        line.append(text, style=TEXT)
        if workspace:
            line.append(f" · {Path(workspace).name or workspace}", style=MUTED)
        return Static(line, classes="gus-line")

    def _scroll_end(self) -> None:
        for body in self.query(".isy-dialog-body"):
            body.scroll_end(animate=False)

    def _status(self, text: str, color: str = MUTED) -> None:
        status = self.query_one("#gus-status", Static)
        status.update(Text(text, style=color))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        if text:
            event.input.value = ""
            self._submit(text)

    def _submit(self, text: str) -> None:
        if self.busy:
            self._status(tr("GUS is still answering."), YELLOW)
            return
        self.busy = True
        self.query_one("#gus-transcript").mount(self._line("user", text, str(self.root)))
        self._status(tr("GUS is thinking…"))
        self._scroll_end()
        self.run_worker(self._ask(text), exclusive=True, group="gus-reply")

    def _work_here(self) -> bool:
        return (self.work is not None and self.target is not None
                and on_gus_branch(self.target))

    async def _ask(self, text: str) -> None:
        report = None
        try:
            if self._work_here():
                reply, report = await self.work(
                    text, self.state, complete=self.complete,
                    on_status=lambda value: self._status(tr("GUS · {value}", value=value)))
            else:
                reply = await gus_reply(self.roots, text, complete=self.complete,
                                        state=self.state, remember=self.remember)
        except GusUnavailable as exc:
            self._status(tr("GUS could not answer · {reason}", reason=tr(str(exc))), RED)
        else:
            self.query_one("#gus-transcript").mount(
                self._line("assistant", reply.text, str(self.root)))
            note = self.report_text(report) if report else ""
            if report and report.get("l0"):
                self._status(note, RED)
            elif note:
                self._status(note, CYAN)
            elif self.target is None:
                self._status(tr("GUS has no editable target yet · open Settings"), MUTED)
            elif self.work is not None and not on_gus_branch(self.target):
                self._status(tr("GUS edits only on a gus/* branch · /gus branch <topic>"), MUTED)
            else:
                self._status(tr("Window unknown: GUS plans for 32k until the real window is known.")
                             if not reply.window_known else "", YELLOW)
        finally:
            self.busy = False
            self._scroll_end()

    async def _run_seal(self) -> None:
        self.busy = True
        self._status(tr("GUS gates running…"))
        try:
            record = await self.seal()
        finally:
            self.busy = False
        if record:
            self._status(self.generation_text(record), CYAN if record["state"] == "SEALED" else RED)
        else:
            self._status("")

    async def _run_undo(self) -> None:
        if self.undo is None or self.busy:
            return
        self.busy = True
        self._status(tr("Undoing GUS's last turn…"))
        try:
            ok = await self.undo()
            self._status(tr("GUS turn restored.") if ok else tr("Nothing undone."),
                         CYAN if ok else YELLOW)
        finally:
            self.busy = False

    async def _pick_provider(self) -> None:
        if self.pick_provider is None:
            return
        new_label = await self.pick_provider()
        if new_label:
            self.model_label = new_label
            for title in self.query(".isy-dialog-title").results(Static):
                title.update(self.dialog_heading())
            self._status(tr("GUS model · {model}", model=new_label), GREEN)
        for field in self.query("#gus-input").results(Input):
            field.focus()

    def dismiss_action(self, action_id: str) -> None:
        if action_id == "gus-provider":
            if self.busy:
                self._status(tr("GUS is still answering."), YELLOW)
            elif self.pick_provider is not None:
                self.run_worker(self._pick_provider(), exclusive=True, group="gus-provider")
            return
        if action_id == "gus-settings":
            if self.busy:
                self._status(tr("GUS is still answering."), YELLOW)
            elif self.settings is not None:
                self.run_worker(self.settings(), exclusive=True, group="gus-settings")
            return
        if action_id == "gus-undo":
            if self.busy:
                self._status(tr("GUS is still answering."), YELLOW)
            else:
                self.run_worker(self._run_undo(), exclusive=True, group="gus-reply")
            return
        if action_id == "gus-seal":
            if self.busy:
                self._status(tr("GUS is still answering."), YELLOW)
            else:
                self.run_worker(self._run_seal(), exclusive=True, group="gus-reply")
            return
        if action_id == "gus-clear":
            self.state.clear()
            self.query_one("#gus-transcript").remove_children()
            self._status(tr("Conversation cleared."))
            return
        self.dismiss(None)


__all__ = ["GUS_COLOR", "GusProviderPickerScreen", "GusScreen"]
