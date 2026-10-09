"""User-only settings and raw-output inspection for native upstream RTK."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from isycode.rtk_integration import Settings, HASH, _directory, _read, savings_label, MAX_CAPTURE_BYTES


class RTKSettingsScreen(ModalScreen):
    CSS = """
    RTKSettingsScreen { align: center middle; background: #000000 58%; }
    #rtk-settings-card { width: 100; max-width: 96%; height: auto; max-height: 90%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #rtk-settings-body { height: auto; max-height: 26; }
    #rtk-identity { height: auto; margin: 1 0; }
    #rtk-state { height: auto; color: #bb8cff; }
    #rtk-settings-actions { height: 3; margin-top: 1; }
    #rtk-settings-actions Button { width: 1fr; margin-right: 1; }
    """
    BINDINGS = [Binding('escape', 'close', 'Close')]

    def __init__(self):
        super().__init__()
        self.candidate: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id='rtk-settings-card'):
            with VerticalScroll(id='rtk-settings-body'):
                yield Static('Native RTK · output compression', markup=False)
                yield Static('Inspecting installation…', id='rtk-state', markup=False)
                yield Static('Checking the binary in the command sandbox…', id='rtk-identity', markup=False)
                yield Static(Text('Compression by RTK · Apache-2.0\nhttps://github.com/rtk-ai/rtk\n\n'
                                  'Off by default. The approved command runs once, unchanged. '
                                  'RTK filters its captured output inside an empty, network-denied sandbox. '
                                  'Authority, Sentinel, approvals and file revocations still apply.\n\n'
                                  'Original output stays private and is linked by SHA-256 to the command receipt. '
                                  'Savings are byte/4 estimates, not provider billing or tokenizer measurements. '
                                  'A changed binary needs a new explicit opt-in.'))
            with Horizontal(id='rtk-settings-actions'):
                yield Button('Enable this binary', id='rtk-enable', disabled=True, variant='success')
                yield Button('Disable', id='rtk-disable')
                yield Button('Close', id='rtk-close')

    def on_mount(self):
        self.run_worker(self._inspect(), group='rtk-settings', exit_on_error=False)

    async def _inspect(self):
        try:
            settings = Settings()
            current = await asyncio.to_thread(settings.load)
            self.candidate = await asyncio.to_thread(settings.inspect)
        except (OSError, ValueError, RuntimeError) as exc:
            self.query_one('#rtk-state', Static).update(Text('Unavailable · ' + str(exc)[:200]))
            return
        value = self.candidate
        self.query_one('#rtk-identity', Static).update(Text(
            value['version'] + '\n' + value['path'] + '\nSHA-256 ' + value['sha256']))
        self.query_one('#rtk-enable', Button).disabled = False
        self._show_state(current)

    def _show_state(self, value):
        root = getattr(self.app, '_workspace_root', Path.cwd())
        label = 'ON · ' if value['enabled'] else 'OFF · '
        self.query_one('#rtk-state', Static).update(Text(label + savings_label(root)))
        if hasattr(self.app, '_refresh_usage'):
            self.app._refresh_usage()

    async def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == 'rtk-close':
            self.dismiss()
            return
        settings = Settings()
        try:
            if event.button.id == 'rtk-enable' and self.candidate is not None:
                value = await asyncio.to_thread(settings.enable, expected=self.candidate)
            elif event.button.id == 'rtk-disable':
                value = await asyncio.to_thread(settings.disable)
            else:
                return
        except (OSError, ValueError, RuntimeError) as exc:
            self.query_one('#rtk-state', Static).update(Text('Not changed · ' + str(exc)[:200]))
            return
        self._show_state(value)

    def action_close(self):
        self.dismiss()


class RTKRawOutputScreen(ModalScreen):
    CSS = """
    RTKRawOutputScreen { align: center middle; background: #000000 58%; }
    #rtk-raw-card { width: 110; max-width: 96%; height: 85%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #rtk-raw-body { height: 1fr; }
    """
    BINDINGS = [Binding('escape', 'close', 'Close')]

    def __init__(self, digest: str, output: str):
        super().__init__()
        self.digest, self.output = digest, output

    def compose(self) -> ComposeResult:
        with Vertical(id='rtk-raw-card'):
            yield Static(Text('Captured original output · SHA-256 ' + self.digest))
            with VerticalScroll(id='rtk-raw-body'):
                yield Static(Text(self.output))
            yield Button('Close', id='rtk-raw-close')

    def on_button_pressed(self, event):
        self.dismiss()

    def action_close(self):
        self.dismiss()


async def command(app, argument: str):
    """A user slash command, never a model tool or an Authority grant."""
    if argument.startswith('recall '):
        digest = argument.removeprefix('recall ').strip()
        if HASH.fullmatch(digest) is None:
            app.notify('Use /rtk recall <64-character SHA-256>', severity='warning')
            return
        try:
            path = _directory('outputs') / (digest + '.bin')
            output = await asyncio.to_thread(_read, path, MAX_CAPTURE_BYTES, private=True)
            if hashlib.sha256(output).hexdigest() != digest:
                raise ValueError('Original output failed SHA-256 verification')
        except (OSError, ValueError) as exc:
            app.notify(str(exc)[:160], severity='warning')
            return
        app.push_screen(RTKRawOutputScreen(digest, output.decode('utf-8', errors='replace')))
        return
    app.push_screen(RTKSettingsScreen())
