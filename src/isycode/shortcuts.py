"""Central, truthful shortcut registry for the ISyCode application shell."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shortcut:
    key: str
    action: str
    label: str
    description: str
    priority: bool = False
    hidden: bool = True


APP_SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("alt+plus,alt+equals,alt+period", "increase_reasoning", "Effort +", "Increase supported reasoning effort", True),
    Shortcut("alt+minus,alt+comma", "decrease_reasoning", "Effort -", "Decrease supported reasoning effort", True),
    Shortcut("ctrl+f", "find_console", "Find", "Search rendered console output", True),
    Shortcut("ctrl+p", "toggle_commands_menu", "Commands", "Open the semantic command palette"),
    Shortcut("ctrl+b", "toggle_sidebar", "Toggle sidebar", "Show or hide the workspace rail"),
    Shortcut("ctrl+l", "focus_input", "Focus composer", "Move focus to the chat composer"),
    Shortcut("ctrl+t", "toggle_tasks", "Tasks", "Fold or expand the agent's task list", True),
    Shortcut("escape", "escape_to_chat", "Back", "Close the current popup and return to chat"),
    Shortcut("f6", "focus_files", "Files", "Open and focus the Files rail", True),
    Shortcut("shift+f6", "focus_overview", "Overview", "Open and focus the Overview rail", True),
    Shortcut("f7", "widen_sidebar", "Widen rail", "Increase the workspace rail width", True),
    Shortcut("shift+f7", "narrow_sidebar", "Narrow rail", "Decrease the workspace rail width", True),
    Shortcut("ctrl+c", "quit", "Quit", "Quit ISyCode"),
)


__all__ = ["APP_SHORTCUTS", "Shortcut"]
