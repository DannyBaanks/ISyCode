#!/usr/bin/env python3
"""ISyCode — minimalist TUI agent on the IsyMotron fabric.

Aesthetic inspired by Crush: banner with diagonal hatch, soft side panel,
gentle colors. But friendlier to normal users than OpenCode's hard black bar.

Chat-first: plain messages stream instantly, model reasoning streams into a
click-to-expand ThoughtBlock (collapsed to "thought for Xs" when done).
IsyMotron ships as a plugin: /plan <intent> runs the capability-fabric flow.
"""
from __future__ import annotations

import os
import sys
import asyncio

ISYMOTRON_ROOT = "/home/danny/Development/ISyCo Git/IsyMotron"
ISYCODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ISYCODE_ROOT)
sys.path.insert(0, ISYMOTRON_ROOT)
sys.path.insert(0, os.path.join(ISYMOTRON_ROOT, "core"))
sys.path.insert(0, os.path.join(ISYMOTRON_ROOT, "hosts"))

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import (Static, Input, Footer, ListView, ListItem,
                             Label, Collapsible)
from rich.text import Text

from agents.planner import Planner, PlanRejected, SYSTEM as PLANNER_SYSTEM
from agents.provider import Provider, ProviderError, Completion
from hosts.simulator.engines import LegacyHost
from relay.loopback import LoopbackRelay
from isymotron.contracts import (HostDescription, HostIdentity,
                                 CapabilityManifest, ExecutionRequest)
from isycode.streaming import stream_complete, StreamError
from isycode.plugins import PluginRegistry, Plugin, PluginCommand
from isycode.gateway_client import GatewayClient
import time as _time


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
                id="mcp-list",
            )
            yield Static("📦 Skills", classes="panel-title")
            yield ListView(
                ListItem(Label("● built-in-browser", classes="skill-online")),
                ListItem(Label("● caveman", classes="skill-online")),
                ListItem(Label("● deep-research", classes="skill-online")),
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


class ThoughtBlock(Collapsible):
    """A reasoning block: streams live, then collapses to 'thought for Xs'.

    Click the title to expand/collapse — exactly the OpenCode/Crush UX,
    native via Textual's Collapsible. The body is passed as a CHILD, not
    via a compose override: Collapsible.compose() builds the internal
    Contents container that '-collapsed' CSS hides — overriding compose
    destroyed it and the block never collapsed.
    """

    def __init__(self, title: str = "thinking...", **kwargs) -> None:
        body = Static(Text("", style=MUTED))
        super().__init__(body, title=title, collapsed=False, **kwargs)
        self._body = body

    def set_text(self, text: str) -> None:
        """Thread-safe entry: replace the reasoning body."""
        self._body.update(Text(text, style=MUTED))

    def collapse_to(self, seconds: float) -> None:
        """Collapse with the elapsed-time title."""
        self.title = f"thought for {seconds:.0f}s"
        self.collapsed = True


class ChatArea(VerticalScroll):
    """Main chat: a scroll of message widgets (Static / ThoughtBlock)."""


class TUIApp(App):
    """ISyCode TUI — Crush-inspired, chat-first, IsyMotron as a plugin."""

    CSS = """
    Screen { background: $surface; }
    #banner {
        dock: top; height: 10; background: $surface; color: $text;
        text-align: center; padding: 0 4;
    }
    #side-panel {
        dock: left; width: 30; height: 100%; background: #16213e;
        border-right: round #2a2a4a; padding: 1 2;
    }
    .panel-title { color: #9b5de5; text-style: bold; padding: 1 0; }
    #mcp-list, #skill-list, #lsp-list {
        height: auto; max-height: 30%; background: transparent;
    }
    .mcp-online { color: #4ade80; }
    .skill-online { color: #4ade80; }
    .lsp-offline { color: #6c757d; }
    #chat {
        height: 100%; background: $surface; padding: 1 2;
    }
    #prompt-input {
        dock: bottom; background: #0f0f23; color: #e0e0e0;
        border: round #2a2a4a; margin: 0 1;
    }
    #prompt-input:focus { border: round #9b5de5; }
    Footer { background: $surface; color: #6c757d; }
    Collapsible { background: transparent; padding: 0; }
    CollapsibleTitle { color: #6c757d; text-style: italic; }
    """

    BINDINGS = [
        Binding("r", "run_plan", "Run plan"),
        Binding("ctrl+p", "command_palette", "Commands"),
        Binding("ctrl+l", "focus_input", "Focus"),
        Binding("ctrl+j", "newline", "Newline"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+g", "more", "More"),
    ]

    def __init__(self):
        super().__init__()
        self._history: list[dict] = []
        self._plugins = PluginRegistry()
        self._last_plan = None
        self._last_relay = None
        self._armed_at: float = 0.0
        self._loop_task: asyncio.Task | None = None
        self._register_builtin_plugins()

    # ── layout ───────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Banner(id="banner")
        yield SidePanel()
        with Vertical(id="main"):
            yield ChatArea(id="chat")
        yield Input(placeholder="Type an intent... (Ctrl+J for newline)",
                    id="prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()
        self._append("◇ ISyCode TUI — IsyMotron capability fabric", CYAN)
        self._append("  Type anything to chat. /plan <intent> uses IsyMotron.", MUTED)
        self.run_worker(self._check_gateway_async(), exclusive=False)
        self.run_worker(self._check_model(), exclusive=False)

    # ── helpers ──────────────────────────────────────────────────

    def _append(self, text: str, color: str = TEXT) -> None:
        """Append a plain message line to the chat."""
        chat = self.query_one(ChatArea)
        chat.mount(Static(Text(text, style=color)))
        chat.scroll_end(animate=False)

    def _mount_thought(self, title: str = "thinking...") -> tuple[ThoughtBlock, ChatArea]:
        chat = self.query_one(ChatArea)
        block = ThoughtBlock(title=title)
        chat.mount(block)
        chat.scroll_end(animate=False)
        return block, chat

    async def _check_gateway_async(self) -> None:
        """Check gateway availability without blocking the event loop."""
        try:
            client = GatewayClient()
            available = await asyncio.to_thread(client.is_available)
            if available:
                self._append("  Gateway: connected", GREEN)
            else:
                self._append("  Gateway: DEGRADED MODE — mutations fail closed", YELLOW)
        except Exception:
            self._append("  Gateway: unavailable — DEGRADED MODE", RED)

    async def _check_model(self) -> None:
        """Eager model check: is the NVIDIA key present and configured?"""
        try:
            key = os.environ.get("ISYMOTRON_API_KEY") or open(
                "/home/danny/Development/NVAPI.txt").read().strip()
            provider = Provider(name="nvidia", api_key=key)
            if provider.configured():
                self._append(
                    f"  Model: {provider.model} via {provider.label} — ready", GREEN)
            else:
                self._append(
                    f"  Model: key found but not configured ({provider.key_env})", YELLOW)
        except FileNotFoundError:
            self._append("  Model: no API key found (NVAPI.txt missing)", RED)
            self._append("  Set ISYMOTRON_API_KEY or place the key file.", MUTED)
        except Exception as e:
            self._append(f"  Model: error — {type(e).__name__}: {e}", RED)

    # ── plugins ──────────────────────────────────────────────────

    def _register_builtin_plugins(self) -> None:
        """IsyMotron ships as a plugin, not as the whole app."""

        async def _plan_cmd(app: "TUIApp", arg: str) -> None:
            if not arg.strip():
                app._append("  Usage: /plan <intent>", MUTED)
                return
            await app._run_plan(arg.strip())

        async def _help_cmd(app: "TUIApp", arg: str) -> None:
            for line in app._plugins.help_text():
                app._append(line, MUTED)
            app._append("  Anything else is plain chat with Nemotron.", MUTED)

        self._plugins.register(Plugin(
            name="isymotron",
            description="capability-fabric planner (Nemotron proposes, host decides)",
            commands=[
                PluginCommand("plan", "plan an intent via IsyMotron", _plan_cmd),
                PluginCommand("help", "list commands", _help_cmd),
            ],
        ))

    # ── input ────────────────────────────────────────────────────

    def on_input_submitted(self, message: Input.Submitted) -> None:
        text = message.value.strip()
        if not text:
            return
        message.input.value = ""
        plugin, cmd, arg = self._plugins.route(text)
        self._append(f"\n> {text}", CYAN)
        if self._loop_task and not self._loop_task.done():
            self._append("  (already running)", YELLOW)
            return
        if cmd is not None:
            self._loop_task = asyncio.create_task(cmd.handler(self, arg))
        else:
            self._loop_task = asyncio.create_task(self._run_chat(text))

    # ── chat (default path) ──────────────────────────────────────

    async def _run_chat(self, text: str) -> None:
        """Instant streaming chat. Reasoning streams into a ThoughtBlock."""
        self._history.append({"role": "user", "content": text})
        block, chat = self._mount_thought()
        reason_buf: list[str] = []
        content_buf: list[str] = []
        holder: dict = {"widget": None}
        t0 = _time.time()

        try:
            key = os.environ.get("ISYMOTRON_API_KEY") or open(
                "/home/danny/Development/NVAPI.txt").read().strip()
            provider = Provider(name="nvidia", api_key=key)

            def _content_line() -> None:
                w = holder["widget"]
                if w is None:
                    w = Static(Text("", style=TEXT))
                    holder["widget"] = w
                    chat.mount(w)
                w.update(Text("".join(content_buf), style=TEXT))
                chat.scroll_end(animate=False)

            def on_chunk(kind: str, chunk: str) -> None:
                if kind == "reasoning":
                    reason_buf.append(chunk)
                    self.call_from_thread(
                        block.set_text, "".join(reason_buf))
                elif kind == "content":
                    content_buf.append(chunk)
                    self.call_from_thread(_content_line)

            def do_stream() -> dict:
                return stream_complete(
                    provider.base_url, provider.api_key, provider.model,
                    self._history, max_tokens=1024, on_chunk=on_chunk)

            try:
                await asyncio.to_thread(do_stream)
            except StreamError:
                comp = await asyncio.to_thread(
                    provider.complete, self._history, max_tokens=1024)
                content_buf.append(comp.text)
                self.call_from_thread(_content_line)

            full = "".join(content_buf).strip()
            if full:
                self._history.append({"role": "assistant", "content": full})
        except Exception as e:
            self._append(f"  Error: {type(e).__name__}: {e}", RED)
        finally:
            block.collapse_to(_time.time() - t0)

    # ── /plan (IsyMotron plugin) ─────────────────────────────────

    async def _run_plan(self, intent: str) -> None:
        """IsyMotron flow: live plan + preflight + R-confirm execution."""
        block, chat = self._mount_thought()
        reason_buf: list[str] = []
        t0 = _time.time()
        try:
            relay = LoopbackRelay()
            legacy = LegacyHost(
                fs={"C:/GAMES/DOOM.EXE": "MZ_BINARY",
                    "C:/GAMES/WOLF3D.EXE": "MZ_X",
                    "C:/NEMO/INBOX/.keep": ""},
                granted=["filesystem.read", "filesystem.write",
                         "apps.launch", "system.info"],
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
                    scopes=c.get("scopes", {}),
                    requires_admin=c.get("requires_admin", False),
                    params=tuple(c.get("params", [])),
                    returns=tuple(c.get("returns", [])),
                ) for c in d["capabilities"]]
                descriptions.append(HostDescription(
                    identity=identity, capabilities=caps,
                    granted=tuple(d.get("granted", [])),
                    bounds=d.get("bounds", {})))

            self._append(f"  Model: {provider.model} via {provider.label}", MUTED)
            self._append("  Host: win98-retrobox (demo) | 4/4 capabilities granted", MUTED)

            cat = Planner.catalogue(descriptions)
            messages = [
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": f"CATALOGUE\n{cat}\n\nREQUEST\n{intent}"},
            ]

            def on_chunk(kind: str, chunk: str) -> None:
                if kind == "reasoning":
                    reason_buf.append(chunk)
                    self.call_from_thread(block.set_text, "".join(reason_buf))
                elapsed = _time.time() - t0
                self.call_from_thread(
                    setattr, block, "title", f"thinking {elapsed:.0f}s")

            def do_stream() -> dict:
                return stream_complete(
                    provider.base_url, provider.api_key, provider.model,
                    messages, max_tokens=2000, on_chunk=on_chunk)

            try:
                result = await asyncio.to_thread(do_stream)
            except StreamError:
                plan = await asyncio.to_thread(
                    planner.plan, intent, descriptions, 2000)
            else:
                usage = result.get("usage") or {}
                completion = Completion(
                    text=result["text"], model=provider.model,
                    provider=provider.name, latency_s=result["latency_s"],
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    finish_reason=result.get("finish_reason"),
                    reasoning=result.get("reasoning", ""))
                plan = Planner.parse(
                    result["text"], descriptions, raw_completion=completion)

            if plan.verdict() == "PLANNED":
                self._append(f"\n  Understood: {plan.understood}", TEXT)
                self._append(f"  Plan ({len(plan.steps)} steps):", YELLOW)
                for i, step in enumerate(plan.steps, 1):
                    params_str = ", ".join(f"{k}={v}" for k, v in step.params.items())
                    self._append(f"    {i}. [{step.host}] {step.capability}({params_str})", TEXT)
                    self._append(f"       ↳ {step.why}", MUTED)
                self._append("\n  This plan carries no authority.", MUTED)
                self._append("  Each step is judged by the host that runs it.", MUTED)
                self._append(f"  Tokens: {plan.completion.prompt_tokens + plan.completion.completion_tokens}", MUTED)
                self._last_plan = plan
                self._last_relay = relay
                self._append("\n  Press R to preflight + run this plan (M1.5 firewall active).", YELLOW)
            else:
                self._append(f"\n  Refused: {plan.refused or 'no plan possible'}", RED)
                self._append("  This is correct behavior, not a failure.", MUTED)

        except PlanRejected as e:
            self._append(f"\n  Plan rejected: {e.reason}", RED)
            self._append(f"  {e.detail}", MUTED)
        except ProviderError as e:
            self._append(f"\n  Provider error: {e}", RED)
            self._append("  Check your API key or try again later.", MUTED)
        except Exception as e:
            self._append(f"\n  Error: {type(e).__name__}: {e}", RED)
        finally:
            block.collapse_to(_time.time() - t0)

    # ── R-confirm execution ──────────────────────────────────────

    def action_run_plan(self) -> None:
        """Double-R confirm: first R arms, second R within 10s executes."""
        if self._last_plan is None or self._last_relay is None:
            self._append("  No plan to run. Use /plan <intent> first.", MUTED)
            return
        now = _time.time()
        if now - self._armed_at > 10.0:
            self._armed_at = now
            n = len(self._last_plan.steps)
            self._append(f"\n  Preflight: {n} steps against granted capabilities.", YELLOW)
            for i, s in enumerate(self._last_plan.steps, 1):
                self._append(f"    {i}. [{s.host}] {s.capability}", TEXT)
            self._append("  Press R again within 10s to execute.", YELLOW)
            return
        self._armed_at = 0.0
        asyncio.create_task(self._execute_stored_plan())

    async def _execute_stored_plan(self) -> None:
        """Lease -> preflight -> execute -> receipt, per step."""
        plan, relay = self._last_plan, self._last_relay
        self._append("\n  Executing...", CYAN)
        ok_count, deny_count = 0, 0
        for i, step in enumerate(plan.steps):
            try:
                lease, decision = relay.request_lease(
                    step.host, "isycode-tui", step.capability, 60.0, {})
                if lease is None:
                    self._append(f"    {i+1}. DENY — no lease: {decision}", RED)
                    deny_count += 1
                    continue
                req = ExecutionRequest.make(
                    host_id=step.host, subject="isycode-tui",
                    capability=step.capability, params=dict(step.params),
                    lease_id=lease.lease_id, plan_id=plan.plan_id)
                receipt = relay.execute(req)
                verdict = receipt.decision.decision.name
                if verdict == "ALLOW":
                    ok_count += 1
                    self._append(f"    {i+1}. ALLOW — receipt {receipt.receipt_id[:12]}", GREEN)
                else:
                    deny_count += 1
                    self._append(f"    {i+1}. DENY — {receipt.decision.reason}", RED)
            except Exception as e:
                deny_count += 1
                self._append(f"    {i+1}. ERROR — {type(e).__name__}: {e}", RED)
        self._append(f"\n  Done: {ok_count} allowed, {deny_count} denied/refused.", CYAN)
        self._last_plan, self._last_relay = None, None


def main():
    app = TUIApp()
    app.run()


if __name__ == "__main__":
    main()
