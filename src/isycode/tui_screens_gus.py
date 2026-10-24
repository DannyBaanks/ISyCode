"""The GUS conversation window (ADR 0011, MK4)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

from isycode.catalog import role_color
from isycode.gus_l0 import on_gus_branch
from isycode.gus_session import GusState, GusUnavailable, gus_reply
from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction
from isycode.tui_theme import CYAN, MUTED, RED, TEXT, YELLOW

# GUS is the maintainer: it takes the maintainer role's identifying color.
GUS_COLOR = role_color("maintainer") or TEXT


class GusScreen(Dialog):
    """Talk to GUS. Its transcript is its own; it never enters the chat history."""

    dialog_width = "wide"
    dialog_height = "fill"
    dialog_cancel_result = None
    # Textual focuses this when the screen activates; without it, a focus asked
    # for during mount can lose to the first focusable widget (the body scroll).
    AUTO_FOCUS = "#gus-input"

    def __init__(self, root: Path, authority_factory: Callable[[], Any], model_label: str,
                 *, initial: str = "", complete=None, work=None, report_text=None,
                 seal=None, generation_text=None) -> None:
        super().__init__()
        self.root = root
        self.authority_factory = authority_factory
        self.model_label = model_label
        self.initial = initial
        self.complete = complete
        # MK5c: on a gus/* branch a turn uses GUS's tools through ``work``.
        self.work = work
        self.report_text = report_text or (lambda report: "")
        # MK5d: ISyCode runs the gates on GUS's committed work.
        self.seal = seal
        self.generation_text = generation_text or (lambda record: record.get("state", ""))
        self.state = GusState(root)
        self.busy = False

    def dialog_heading(self) -> str:
        return tr("GUS · {model}", model=self.model_label)

    def dialog_hint(self) -> str:
        return tr("Enter send · Esc close · on a gus/* branch GUS edits with its tools; elsewhere it reads and answers")

    def compose_body(self) -> ComposeResult:
        with Vertical(id="gus-transcript"):
            for entry in self.state.transcript():
                yield self._line(entry["role"], entry["text"])
        yield Static("", id="gus-status", markup=False)
        yield Input(placeholder=tr("Write to GUS…"), id="gus-input")

    def dialog_actions(self) -> tuple[DialogAction, ...]:
        # Refuse-first (I-03): the harmless action comes first; Clear is never focused.
        actions = (DialogAction("gus-close", tr("Close")),
                   DialogAction("gus-clear", tr("Clear conversation")))
        if self.seal is not None:
            actions += (DialogAction("gus-seal", tr("Run the gates")),)
        return actions

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
    def _line(role: str, text: str) -> Static:
        speaker = tr("You") if role == "user" else "GUS"
        line = Text(f"{speaker} · ", style=f"bold {GUS_COLOR}" if role != "user" else f"bold {TEXT}")
        line.append(text, style=TEXT)
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
        self.query_one("#gus-transcript").mount(self._line("user", text))
        self._status(tr("GUS is thinking…"))
        self._scroll_end()
        self.run_worker(self._ask(text), exclusive=True, group="gus-reply")

    async def _ask(self, text: str) -> None:
        report = None
        try:
            if self.work is not None and on_gus_branch(self.root):
                reply, report = await self.work(
                    text, self.state, complete=self.complete,
                    on_status=lambda value: self._status(tr("GUS · {value}", value=value)))
            else:
                reply = await gus_reply(self.root, self.authority_factory(), text,
                                        complete=self.complete, state=self.state)
        except GusUnavailable as exc:
            self._status(tr("GUS could not answer · {reason}", reason=tr(str(exc))), RED)
        else:
            self.query_one("#gus-transcript").mount(self._line("assistant", reply.text))
            note = self.report_text(report) if report else ""
            if report and report.get("l0"):
                self._status(note, RED)
            elif note:
                self._status(note, CYAN)
            elif self.work is not None and not on_gus_branch(self.root):
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

    def dismiss_action(self, action_id: str) -> None:
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


__all__ = ["GUS_COLOR", "GusScreen"]
