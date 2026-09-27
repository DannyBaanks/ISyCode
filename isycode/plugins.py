#!/usr/bin/env python3
"""ISyCode plugin system — IsyMotron is one plugin, not the whole app.

The TUI core is a fast streaming chat. Plugins register commands that
take over specific inputs. The default path never touches the planner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Awaitable


@dataclass
class PluginCommand:
    """One slash-command handled by a plugin."""
    name: str          # e.g. "plan"
    description: str   # shown in /help
    handler: Callable  # async (app, arg: str) -> None


@dataclass
class Plugin:
    """A named bundle of commands."""
    name: str
    description: str
    commands: list[PluginCommand] = field(default_factory=list)


class PluginRegistry:
    """Command router. First match wins. No match -> default chat."""

    def __init__(self):
        self._commands: dict[str, tuple[Plugin, PluginCommand]] = {}

    def register(self, plugin: Plugin) -> None:
        for cmd in plugin.commands:
            if cmd.name in self._commands:
                raise ValueError(f"command already registered: /{cmd.name}")
            self._commands[cmd.name] = (plugin, cmd)

    def route(self, text: str):
        """Returns (plugin, command, arg) or (None, None, text)."""
        if not text.startswith("/"):
            return None, None, text
        parts = text[1:].split(None, 1)
        name = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if name in self._commands:
            plugin, cmd = self._commands[name]
            return plugin, cmd, arg
        return None, None, text

    def help_text(self) -> list[str]:
        lines = ["  Available commands:"]
        for name, (plugin, cmd) in sorted(self._commands.items()):
            lines.append(f"    /{name} — {cmd.description} [{plugin.name}]")
        return lines
