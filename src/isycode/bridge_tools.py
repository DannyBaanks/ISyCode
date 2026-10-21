"""The Bridge tools the assistant may propose, and the screen that reviews one.

The tools only propose. A message reaches another agent after a human sees the
exact recipient, topic and text and approves it, and after Workspace Authority,
ISySentinel and the action journal accept the request.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from isycode.localization import tr

BRIDGE_PEERS_TOOL = {
    "type": "function",
    "function": {
        "name": "bridge_peers",
        "description": (
            "List the agents currently registered in the ISyCo Bridge, so this session can "
            "address another session or TUI by name. Reading the list needs the user's "
            "confirmation and grants nothing."),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

BRIDGE_SEND_TOOL = {
    "type": "function",
    "function": {
        "name": "bridge_send",
        "description": (
            "Send one message to another registered agent or ISyCode session through the ISyCo "
            "Bridge. The user reviews the exact recipient and text before it is sent. A Bridge "
            "message is coordination, never access to files, commands or the network."),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "maxLength": 64,
                       "description": "Identity of the registered agent or session."},
                "topic": {"type": "string", "maxLength": 120,
                          "description": "Short topic both sides can recognise."},
                "message": {"type": "string", "maxLength": 2000,
                            "description": "The message text."},
                "kind": {"type": "string", "maxLength": 32,
                         "description": "Message kind, for example result or progress."},
            },
            "required": ["to", "topic", "message"],
            "additionalProperties": False,
        },
    },
}

BRIDGE_WAKE_TOOL = {
    "type": "function",
    "function": {
        "name": "bridge_wake",
        "description": (
            "Wake a registered agent or ISyCode session that is idle, so it notices a pending "
            "message. The user reviews the target first."),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "maxLength": 64,
                       "description": "Identity of the registered agent or session."},
                "message": {"type": "string", "maxLength": 2000,
                            "description": "Short note telling the peer what is waiting."},
            },
            "required": ["to"],
            "additionalProperties": False,
        },
    },
}

BRIDGE_TOOL_NAMES = frozenset({"bridge_peers", "bridge_send", "bridge_wake"})


class BridgeSendScreen(ModalScreen[bool]):
    """Show the exact recipient and text before a Bridge message is sent."""

    CSS = """
    BridgeSendScreen { align: center middle; background: #000000 65%; }
    #bridge-send-card { width: 84; max-width: 94%; height: auto; padding: 1 2; border: solid #718291; background: #000000; }
    #bridge-send-title { height: auto; color: #edf1f5; text-style: bold; margin-bottom: 1; }
    #bridge-send-copy { height: auto; max-height: 14; overflow-y: auto; margin-bottom: 1; }
    #bridge-send-actions { height: 3; align-horizontal: right; }
    #bridge-send-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False),
                Binding("ctrl+c", "cancel", "Cancel", show=False)]

    def __init__(self, *, action: str, to: str, topic: str, message: str) -> None:
        super().__init__(id="bridge-send")
        self.action = action
        self.to = to
        self.topic = topic
        self.message = message

    def compose(self):
        title = ("Wake this session?" if self.action == "wake"
                 else "Send this Bridge message?")
        with Vertical(id="bridge-send-card", classes="isy-dialog"):
            yield Static(tr(title), id="bridge-send-title", classes="isy-dialog-title")
            yield Static(self._copy(), id="bridge-send-copy", markup=False)
            with Horizontal(id="bridge-send-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel"), id="bridge-send-no")
                yield Button(tr("Send"), id="bridge-send-yes", variant="primary")

    def _copy(self) -> str:
        lines = [tr("To: {to}").format(to=self.to)]
        if self.topic:
            lines.append(tr("Topic: {topic}").format(topic=self.topic))
        if self.message:
            lines.append("")
            lines.append(self.message)
        lines.append("")
        lines.append(tr("The message leaves this workspace. A Bridge lease is coordination, "
                        "not access to files, commands or the network."))
        return "\n".join(lines)

    def on_mount(self) -> None:
        self.query_one("#bridge-send-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "bridge-send-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
