"""Interactive human shell modal for sudo / TTY commands."""
from __future__ import annotations

import sys
from contextlib import nullcontext
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from isycode.human_shell import run_human_shell_command
from isycode.tui_theme import ACCENT, GREEN, MUTED, TEXT, YELLOW


class HumanShellScreen(ModalScreen[dict[str, Any] | None]):
    """Modal console where the human runs commands and shares sanitized output."""

    DEFAULT_CSS = """
    HumanShellScreen { align: center middle; background: rgba(0, 0, 0, 0.72); }
    #human-shell-card {
        width: 108; max-width: 96%; height: 90%; max-height: 40;
        padding: 1 2; border: solid #00d7ff; background: #000000; color: #ffffff;
    }
    #human-shell-reason { height: auto; max-height: 4; margin-bottom: 1; color: #a8b7c5; }
    #human-shell-log-scroll {
        height: 1fr; min-height: 6; border: solid #46545f; padding: 0 1;
        margin-bottom: 1; background: #050709;
    }
    #human-shell-output { height: auto; color: #ffffff; }
    #human-shell-suggestions { height: auto; max-height: 9; margin-bottom: 1; overflow-y: auto; }
    .human-shell-suggest {
        width: 100%; height: auto; min-height: 1; margin-bottom: 0;
        border: none; background: #0d141a; color: #00d7ff; text-align: left;
    }
    .human-shell-suggest:hover, .human-shell-suggest:focus { background: #002c36; color: #ffffff; }
    #human-shell-input { margin-bottom: 1; border: solid #00d7ff; background: #000000; color: #ffffff; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        reason: str,
        commands: list[str] | None = None,
        cwd: str = ".",
        *,
        executor=run_human_shell_command,
    ) -> None:
        super().__init__()
        self.reason = reason
        self.suggested_commands = list(commands or [])
        self.cwd = cwd
        self._executor = executor
        self.runs: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="human-shell-card", classes="isy-dialog"):
            yield Static(
                Text("Consola interactiva (sudo / shell)", style=f"bold {ACCENT}"),
                classes="isy-dialog-title",
            )
            yield Static(
                Text(f"{self.reason}\ncwd: {self.cwd}", style=MUTED),
                id="human-shell-reason",
            )
            with VerticalScroll(id="human-shell-log-scroll"):
                yield Static(
                    Text("Sin comandos ejecutados aún. Elige una sugerencia o escribe abajo y presiona Enter.", style=MUTED),
                    id="human-shell-output",
                )
            if self.suggested_commands:
                with Vertical(id="human-shell-suggestions"):
                    yield Static(
                        Text("Comandos sugeridos por el modelo (clic para copiar a la caja):", style=YELLOW),
                    )
                    for idx, cmd in enumerate(self.suggested_commands):
                        yield Button(
                            f"[{idx + 1}] {cmd}",
                            id=f"human-shell-suggest-{idx}",
                            classes="human-shell-suggest",
                        )
            yield Input(
                value=self.suggested_commands[0] if self.suggested_commands else "",
                placeholder="Escribe el comando y presiona Enter para ejecutar...",
                id="human-shell-input",
            )
            with Horizontal(classes="isy-dialog-actions"):
                yield Button("Enviar salida al modelo", id="human-shell-send", variant="primary")
                yield Button("Cancelar", id="human-shell-cancel")

    def on_mount(self) -> None:
        self.query_one("#human-shell-input", Input).focus()

    def _refresh_log(self) -> None:
        if not self.runs:
            return
        rendered = Text()
        for idx, run in enumerate(self.runs):
            if idx:
                rendered.append("\n")
            rendered.append(f"$ {run['command']}\n", style=f"bold {ACCENT}")
            if run["output"]:
                rendered.append(run["output"].rstrip("\n") + "\n", style=TEXT)
            status_style = GREEN if run["exit_code"] == 0 else YELLOW
            rendered.append(f"[exit {run['exit_code']}]\n", style=status_style)
        self.query_one("#human-shell-output", Static).update(rendered)
        self.query_one("#human-shell-log-scroll", VerticalScroll).scroll_end(animate=False)

    def _run_command(self, command: str) -> None:
        command = command.strip()
        if not command:
            return
        can_suspend = (
            not getattr(self.app, "is_headless", False)
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        )
        ctx = self.app.suspend() if can_suspend else nullcontext()
        with ctx:
            exit_code, output = self._executor(command, self.cwd, use_pty=can_suspend)
        self.runs.append({"command": command, "exit_code": exit_code, "output": output})
        self._refresh_log()
        inp = self.query_one("#human-shell-input", Input)
        inp.value = ""
        inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "human-shell-input":
            event.stop()
            self._run_command(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("human-shell-suggest-"):
            idx = int(btn_id.removeprefix("human-shell-suggest-"))
            if 0 <= idx < len(self.suggested_commands):
                inp = self.query_one("#human-shell-input", Input)
                inp.value = self.suggested_commands[idx]
                inp.cursor_position = len(inp.value)
                inp.focus()
            return
        if btn_id == "human-shell-send":
            self.dismiss({"status": "completed" if self.runs else "no_commands_run", "runs": list(self.runs)})
            return
        if btn_id == "human-shell-cancel":
            self.dismiss({"status": "cancelled", "runs": list(self.runs)})

    def action_cancel(self) -> None:
        self.dismiss({"status": "cancelled", "runs": list(self.runs)})
