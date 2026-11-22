"""Tests for the interactive human_shell sudo/TTY console."""
from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import Input, Static

from isycode.human_shell import is_sudo_or_tty_error, validate_human_shell
from isycode.tui_screens_shell import HumanShellScreen


def test_validate_human_shell_and_sudo_detection():
    req = validate_human_shell({
        "reason": "Need sudo to inspect systemd",
        "commands": ["sudo systemctl status foo", "echo ok\x1b[2J"],
    })
    assert req["reason"] == "Need sudo to inspect systemd"
    assert req["commands"][0] == "sudo systemctl status foo"
    assert "\x1b" not in req["commands"][1]
    assert is_sudo_or_tty_error(1, "sudo: a terminal is required to read the password")
    assert not is_sudo_or_tty_error(0, "sudo: a terminal is required")


def test_human_shell_screen_runs_human_command_and_returns_output():
    executed = []
    results = []

    def fake_executor(command: str, cwd: str, *, use_pty: bool = True):
        executed.append((command, cwd, use_pty))
        return 0, f"ran:{command}\n"

    class Host(App):
        def on_mount(self):
            self.push_screen(
                HumanShellScreen(
                    "Need elevated permissions",
                    commands=["sudo id", "sudo systemctl status foo"],
                    cwd="/tmp",
                    executor=fake_executor,
                ),
                results.append,
            )

    async def scenario():
        async with Host().run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Click second suggested command above the input box.
            await pilot.click("#human-shell-suggest-1")
            await pilot.pause()
            inp = pilot.app.screen.query_one("#human-shell-input", Input)
            assert inp.value == "sudo systemctl status foo"
            await pilot.press("enter")
            await pilot.pause()
            assert executed == [("sudo systemctl status foo", "/tmp", False)]
            log_text = str(pilot.app.screen.query_one("#human-shell-output", Static).render())
            assert "ran:sudo systemctl status foo" in log_text
            await pilot.click("#human-shell-send")
            await pilot.pause()

    asyncio.run(scenario())
    assert results == [{
        "status": "completed",
        "runs": [{"command": "sudo systemctl status foo", "exit_code": 0, "output": "ran:sudo systemctl status foo\n"}],
    }]
