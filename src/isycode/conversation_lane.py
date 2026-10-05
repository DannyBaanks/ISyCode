"""One in-process turn per conversation.

Switching the visible chat parks the previous lane. It does not cancel that
turn, and it does not add an authority owner. The ContextVar is set before
asyncio.create_task so the turn and the tasks it starts keep writing to the
lane they began on.
"""
from __future__ import annotations

from contextvars import ContextVar

from isycode.throughput import ThroughputMeter
from isycode.usage import UsageLedger


conversation_lane_context: ContextVar = ContextVar("isycode_conversation_lane", default=None)


class ConversationLane:
    """Transcript, queue, and live turn for one conversation."""

    def __init__(self, key: str):
        self.key = key
        self.session_id = None if str(key).startswith("memory") else key
        self.history: list = []
        self.tool_history: list = []
        self.conversation_summary = ""
        self.usage = UsageLedger()
        self.last_context_input_tokens = None
        self.throughput = ThroughputMeter()
        self.queued_messages: list = []
        self.pending_steering: list = []
        self.loop_task = None
        self.chat_turn_task = None
        self.chat_request_task = None
        self.retry_prompt = None
        self.idea_box = ""
        self.draft_text = ""
        self.steering_try_active = False
        self.pending_user_sent_at = None
        self.session_save_warned = False
        self.agent_tasks: list = []
        self.active_chat_provider = None
        self.steering_restore_positions: dict = {}
        self.selected_queued_message = None
        self.idea_nudge_due = False
        self.activity_message = "Chat ready"
        self.activity_color = None
        # ("user"|"note"|"assistant", text, sent_at or color)
        self.lines: list = []
        self.partial = ""
        self.partial_reason = ""
        self.stream_widget = None
        self.stream_block = None


LANE_FIELDS = (
    ("_history", "history"),
    ("_tool_history", "tool_history"),
    ("_conversation_summary", "conversation_summary"),
    ("_usage", "usage"),
    ("_last_context_input_tokens", "last_context_input_tokens"),
    ("_throughput", "throughput"),
    ("_queued_messages", "queued_messages"),
    ("_pending_steering", "pending_steering"),
    ("_loop_task", "loop_task"),
    ("_chat_turn_task", "chat_turn_task"),
    ("_chat_request_task", "chat_request_task"),
    ("_retry_prompt", "retry_prompt"),
    ("_idea_box", "idea_box"),
    ("_draft_text", "draft_text"),
    ("_steering_try_active", "steering_try_active"),
    ("_pending_user_sent_at", "pending_user_sent_at"),
    ("_session_save_warned", "session_save_warned"),
    ("_agent_tasks", "agent_tasks"),
    ("_active_chat_provider", "active_chat_provider"),
    ("_steering_restore_positions", "steering_restore_positions"),
    ("_selected_queued_message", "selected_queued_message"),
    ("_idea_nudge_due", "idea_nudge_due"),
)


def lane_property(field: str) -> property:
    """Route one TUI attribute to whichever lane is running this task."""

    def getter(self):
        return getattr(self._active_lane(), field)

    def setter(self, value) -> None:
        setattr(self._active_lane(), field, value)

    return property(getter, setter)


def fresh_memory_key(app) -> str:
    if "memory" not in app._lanes:
        return "memory"
    number = 2
    while f"memory-{number}" in app._lanes:
        number += 1
    return f"memory-{number}"


def rekey_lane(app, lane: ConversationLane, new_id) -> None:
    """Point a memory lane at a saved id without replacing the lane object."""
    if new_id == "":
        new_id = None
    if new_id == lane.session_id and (new_id is None or lane.key == new_id):
        lane.session_id = new_id
        return
    if not new_id:
        lane.session_id = None
        if str(lane.key).startswith("memory"):
            return
        old = lane.key
        if app._lanes.get(old) is lane:
            del app._lanes[old]
        fresh = fresh_memory_key(app)
        lane.key = fresh
        app._lanes[fresh] = lane
        if app._foreground_key == old:
            app._foreground_key = fresh
        return
    other = app._lanes.get(new_id)
    if other is not None and other is not lane:
        lane.session_id = new_id
        return
    old = lane.key
    if app._lanes.get(old) is lane:
        del app._lanes[old]
    lane.key = new_id
    lane.session_id = new_id
    app._lanes[new_id] = lane
    if app._foreground_key == old:
        app._foreground_key = new_id


def open_lane(app, session_id: str | None) -> ConversationLane:
    """Return the lane for a saved id, or a new unsaved conversation."""
    if session_id and session_id in app._lanes:
        return app._lanes[session_id]
    key = fresh_memory_key(app) if not session_id or session_id == "memory" else session_id
    if key in app._lanes:
        key = fresh_memory_key(app)
    lane = ConversationLane(key)
    app._lanes[key] = lane
    return lane
