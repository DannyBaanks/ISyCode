"""The Bridge tools the assistant may propose, and the screen that reviews one.

The tools only propose. A message reaches another agent after a human sees the
exact recipient, topic and text and approves it, and after Workspace Authority,
ISySentinel and the action journal accept the request.
"""
from __future__ import annotations

from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction

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


class BridgeSendScreen(Dialog):
    """Show the exact recipient and text before a Bridge message is sent."""

    dialog_title = "Send this Bridge message?"
    dialog_width = "normal"
    dialog_tone = "approval"
    dialog_cancel_result = False

    def __init__(self, *, action: str, to: str, topic: str, message: str) -> None:
        self.action = action
        self.to = to
        self.topic = topic
        self.message = message
        super().__init__(id="bridge-send")

    def dialog_heading(self) -> str:
        return tr("Wake this session?") if self.action == "wake" else tr("Send this Bridge message?")

    def dialog_note(self) -> str:
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

    def dialog_actions(self):
        return (
            DialogAction("bridge-send-no", tr("Cancel"), focused=True),
            DialogAction("bridge-send-yes", tr("Send"), "primary"),
        )

    def dismiss_action(self, action_id: str) -> None:
        self.dismiss(action_id == "bridge-send-yes")


