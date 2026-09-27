#!/usr/bin/env python3
"""ISyCode — minimalist TUI agent on the IsyMotron fabric.

Aesthetic inspired by Crush: banner with diagonal hatch, soft side panel,
gentle colors. But friendlier to normal users than OpenCode's hard black bar.
"""
from __future__ import annotations

import os
import sys
import asyncio
from typing import Any

ISYMOTRON_ROOT = "/home/danny/Development/ISyCo Git/IsyMotron"
sys.path.insert(0, ISYMOTRON_ROOT)
sys.path.insert(0, os.path.join(ISYMOTRON_ROOT, "core"))
sys.path.insert(0, os.path.join(ISYMOTRON_ROOT, "hosts"))

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, Footer, Header, ListView, ListItem, Label
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.color import Color
from rich.text import Text
from rich.panel import Panel
from rich.syntax import Syntax

from agents.planner import Planner, PlanRejected
from agents.provider import Provider, ProviderError
from hosts.simulator.engines import LegacyHost
from relay.loopback import LoopbackRelay
from isymotron.contracts import HostDescription, HostIdentity, CapabilityManifest


# ── Palette (Crush-inspired but softer) ───────────────────────────
BG = "#1a1a2e"        # deep navy-black
BG2 = "#16213e"       # panel background
ACCENT = "#e94560"    # crush pink-red (softened)
ACCENT2 = "#9b5de5"   # purple accent
TEXT = "#e0e0e0"      # main text
MUTED = "#6c757d"     # muted
GREEN = "#4ade80"     # success / granted
YELLOW = "#fbbf24"    # warning / plan
RED = "#f87171"       # error / denied
CYAN = "#22d3ee"      # info / host


# ── Banner: literal, exact. Spells ISYCODE. ──────────────────────
BANNER = r"""
 ██╗███████╗██╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗
 ██║██╔════╝╚██╗ ██╔╝██╔════╝██╔═══██╗██╔══██╗██╔════╝
 ██║███████╗ ╚████╔╝ ██║     ██║   ██║██║  ██║█████╗
 ██║╚════██║  ╚██╔╝  ██║     ██║   ██║██║  ██║██╔══╝
 ██║███████║   ██║   ╚██████╗╚██████╔╝██████╔╝███████╗
 ╚═╝╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝
"""


def banner_text() -> Text:
    """Crush-style banner: bold letters with diagonal hatch."""
    t = Text()
    for line in BANNER.strip("\n").split("\n"):
        t.append(line + "\n", style="bold #e94560")
    t.append("\n  One AI. Many hosts. One capability fabric.", style="italic #6c757d")
    return t


class Banner(Static):
    """Top banner with Crush-style ASCII art."""

    def render(self) -> Text:
        return banner_text()


class SidePanel(Static):
    """Left panel: MCPs, Skills, LSPs — soft, not a hard black bar."""

    def compose(self) -> ComposeResult:
        with Vertical(id="side-panel"):
            yield Static("🔌 MCPs", classes="panel-title")
            yield ListView(
                ListItem(Label("● isyco-gateway", classes="mcp-online")),
                ListItem(Label("● playwright", classes="mcp-online")),
                ListItem(Label("○ isyco-gateway", classes="mcp-error")),
                id="mcp-list",
            )
            yield Static("📦 Skills", classes="panel-title")
            yield ListView(
                ListItem(Label("● built-in-browser", classes="skill-online")),
                ListItem(Label("● caveman", classes="skill-online")),
                ListItem(Label("● crush-config", classes="skill-online")),
                ListItem(Label("● deep-research", classes="skill-online")),
                ListItem(Label("● docs", classes="skill-online")),
                id="skill-list",
            )
            yield Static("🔧 LSPs", classes="panel-title")
            yield ListView(
                ListItem(Label("○ None", classes="lsp-offline")),
                id="lsp-list",
            )

    def on_mount(self) -> None:
        self.styles.background = BG2
        self.styles.border = ("round", "#2a2a4a")


class ChatArea(Static):
    """Main chat area: messages, plans, receipts."""

    messages: reactive[list[str]] = reactive(list)

    def render(self) -> Text:
        out = Text()
        for m in self.messages:
            out.append(m + "\n")
        return out


class TUIApp(App):
    """ISyCode TUI — Crush-inspired, user-friendly."""

    CSS = """
    Screen {
        background: $surface;
    }
    #banner {
        dock: top;
        height: 10;
        background: $surface;
        color: $text;
        text-align: center;
        padding: 0 4;
    }
    #side-panel {
        dock: left;
        width: 30%;
        height: 100%;
        background: #16213e;
        border-right: round #2a2a4a;
        padding: 1 2;
    }
    .panel-title {
        color: #9b5de5;
        text-style: bold;
        padding: 1 0;
    }
    #mcp-list, #skill-list, #lsp-list {
        height: auto;
        max-height: 30%;
        background: transparent;
    }
    .mcp-online { color: #4ade80; }
    .mcp-error { color: #f87171; }
    .skill-online { color: #4ade80; }
    .lsp-offline { color: #6c757d; }
    #chat {
        height: 100%;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }
    #input-area {
        dock: bottom;
        height: 3;
        background: $surface;
        border-top: round #2a2a4a;
        padding: 0 2;
    }
    #prompt-input {
        background: #0f0f23;
        color: #e0e0e0;
        border: round #2a2a4a;
    }
    #prompt-input:focus {
        border: round #9b5de5;
    }
    Footer {
        background: $surface;
        color: #6c757d;
    }
    """

    BINDINGS = [
        Binding("ctrl+p", "command_palette", "Commands"),
        Binding("ctrl+l", "focus_input", "Focus"),
        Binding("ctrl+j", "newline", "Newline"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+g", "more", "More"),
    ]

    def __init__(self):
        super().__init__()
        self.chat_messages: list[str] = []
        self._loop_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Banner(id="banner")
        yield SidePanel()
        with Vertical(id="main"):
            yield ChatArea(id="chat")
        yield Input(placeholder="Type an intent... (Ctrl+J for newline)", id="prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()
        self._append("◇ ISyCode TUI — IsyMotron capability fabric", CYAN)
        self._append("  Type an intent. Nemotron proposes. The host decides.", MUTED)
        self._append("  Awaiting model connection...", MUTED)

    def _append(self, text: str, color: str = TEXT) -> None:
        self.chat_messages.append(f"[{color}]{text}[/{color}]")
        try:
            self.query_one(ChatArea).messages = self.chat_messages
        except NoMatches:
            pass

    def on_submitted(self, message: Input.Submitted) -> None:
        intent = message.value.strip()
        if not intent:
            return
        message.input.value = ""
        self._append(f"\n> {intent}", CYAN)
        self._append("  Thinking...", MUTED)
        if self._loop_task and not self._loop_task.done():
            self._append("  (already running)", YELLOW)
            return
        self._loop_task = asyncio.create_task(self._run_plan(intent))

    async def _run_plan(self, intent: str) -> None:
        try:
            relay = LoopbackRelay()
            legacy = LegacyHost(
                fs={"C:/GAMES/DOOM.EXE": "MZ_BINARY", "C:/GAMES/WOLF3D.EXE": "MZ_X",
                    "C:/NEMO/INBOX/.keep": ""},
                granted=["filesystem.read", "filesystem.write", "apps.launch", "system.info"],
                grant_scopes={
                    "filesystem.read": {"roots": ["C:/GAMES"]},
                    "filesystem.write": {"roots": ["C:/NEMO/INBOX"]},
                    "apps.launch": {"allowlist": ["DOOM.EXE"]},
                    "system.info": {},
                })
            relay.attach(legacy)

            key = os.environ.get("ISYMOTRON_API_KEY") or open(
                "/home/danny/Development/NVAPI.txt").read().strip()
            provider = Provider(name="nvidia", api_key=key)
            planner = Planner(provider)

            descriptions = []
            for h in relay.hosts():
                d = relay.describe(h["host_id"])
                identity = HostIdentity(**d["identity"])
                caps = [CapabilityManifest(
                    id=c["id"], version=c["version"], summary=c["summary"],
                    scopes=c.get("scopes", {}), requires_admin=c.get("requires_admin", False),
                    params=tuple(c.get("params", [])), returns=tuple(c.get("returns", [])),
                ) for c in d["capabilities"]]
                descriptions.append(HostDescription(
                    identity=identity, capabilities=caps,
                    granted=tuple(d.get("granted", [])), bounds=d.get("bounds", {}),
                ))

            self._append(f"  Model: {provider.model} via {provider.label}", MUTED)
            self._append(f"  Host: win98-retrobox (demo) | 4/4 capabilities granted", MUTED)

            plan = planner.plan(intent, descriptions, max_tokens=2000)

            if plan.verdict() == "PLANNED":
                self._append(f"\n  Understood: {plan.understood}", TEXT)
                self._append(f"  Plan ({len(plan.steps)} steps):", YELLOW)
                for i, step in enumerate(plan.steps, 1):
                    params_str = ", ".join(f"{k}={v}" for k, v in step.params.items())
                    self._append(f"    {i}. [{step.host}] {step.capability}({params_str})", TEXT)
                    self._append(f"       ↳ {step.why}", MUTED)
                self._append(f"\n  This plan carries no authority.", MUTED)
                self._append(f"  Each step is judged by the host that runs it.", MUTED)
                self._append(f"  Tokens: {plan.completion.prompt_tokens + plan.completion.completion_tokens}", MUTED)
                self._append(f"\n  [Run this plan] would execute here (M1.5 safety gate pending)", MUTED)
            else:
                self._append(f"\n  Refused: {plan.refused or 'no plan possible'}", RED)
                self._append(f"  This is correct behavior, not a failure.", MUTED)

        except PlanRejected as e:
            self._append(f"\n  Plan rejected: {e.reason}", RED)
            self._append(f"  {e.detail}", MUTED)
        except ProviderError as e:
            self._append(f"\n  Provider error: {e}", RED)
            self._append(f"  Check your API key or try again later.", MUTED)
        except Exception as e:
            self._append(f"\n  Error: {type(e).__name__}: {e}", RED)


def main():
    app = TUIApp()
    app.run()


if __name__ == "__main__":
    main()
