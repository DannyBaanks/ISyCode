"""Human-operated interactive shell console for sudo/TTY commands.

Suggested commands from the model are displayed above the input box, but ONLY
commands explicitly submitted by the human at the keyboard are executed.
"""
from __future__ import annotations

import os
import select
import subprocess
import sys
from typing import Any

from isycode.terminal_safety import strip_controls

HUMAN_SHELL_TOOL_NAME = "human_shell"
MAX_REASON_CHARS = 500
MAX_SUGGESTIONS = 10
MAX_COMMAND_CHARS = 2000
MAX_OUTPUT_CHARS = 16000

HUMAN_SHELL_TOOL = {
    "type": "function",
    "function": {
        "name": HUMAN_SHELL_TOOL_NAME,
        "description": (
            "Open an interactive shell console modal for the person at the keyboard "
            "when elevated permissions (sudo), an interactive TTY, or manual shell "
            "steps are needed. Suggested commands are shown above the input box for "
            "the human to inspect, edit, and run; the captured sanitized output is "
            "returned to you."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why human shell / sudo interaction is needed.",
                },
                "commands": {
                    "type": "array",
                    "maxItems": MAX_SUGGESTIONS,
                    "items": {
                        "type": "string",
                        "description": "One suggested shell command for the human.",
                    },
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory path.",
                },
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
}

_SUDO_TTY_MARKERS = (
    "sudo: a terminal is required",
    "sudo: no password was provided",
    "a password is required",
    "no tty present",
    "sorry, you must have a tty",
)


def is_sudo_or_tty_error(exit_code: int | None, output: str) -> bool:
    """Return True when a non-zero command failed because sudo/TTY was missing."""
    if exit_code == 0 or not output:
        return False
    lowered = output.lower()
    return any(marker in lowered for marker in _SUDO_TTY_MARKERS)


def validate_human_shell(arguments: Any) -> dict[str, Any]:
    """Validate and bound arguments for ``human_shell``."""
    if not isinstance(arguments, dict) or set(arguments) - {"reason", "commands", "cwd"}:
        raise ValueError("human_shell accepts only reason, optional commands, and optional cwd")
    reason = arguments.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("human_shell requires a non-empty reason")
    cleaned_reason = strip_controls(" ".join(reason.split()))[:MAX_REASON_CHARS].strip()
    raw_commands = arguments.get("commands") or []
    if not isinstance(raw_commands, list) or len(raw_commands) > MAX_SUGGESTIONS:
        raise ValueError(f"human_shell accepts at most {MAX_SUGGESTIONS} suggested commands")
    commands: list[str] = []
    for item in raw_commands:
        if not isinstance(item, str) or "\x00" in item:
            raise ValueError("each suggested command must be a clean string")
        cmd = strip_controls(item).strip()[:MAX_COMMAND_CHARS]
        if cmd:
            commands.append(cmd)
    cwd = arguments.get("cwd")
    if cwd is not None:
        if not isinstance(cwd, str) or "\x00" in cwd:
            raise ValueError("cwd must be a string path")
        cwd = strip_controls(cwd).strip() or None
    return {"reason": cleaned_reason, "commands": commands, "cwd": cwd}


def run_human_shell_command(
    command: str,
    cwd: str,
    *,
    use_pty: bool = True,
) -> tuple[int, str]:
    """Run one human-submitted command, using a real PTY on POSIX when possible."""
    if os.name == "posix" and use_pty and sys.stdin.isatty() and sys.stdout.isatty():
        import pty
        import termios
        import tty

        master_fd, slave_fd = pty.openpty()
        old_tty = None
        try:
            old_tty = termios.tcgetattr(sys.stdin.fileno())
            tty.setraw(sys.stdin.fileno())
        except termios.error:
            old_tty = None
        captured = bytearray()
        timed_out = False
        import time as _time
        started = _time.monotonic()
        max_buffer = MAX_OUTPUT_CHARS * 4
        try:
            try:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=cwd,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True,
                )
            except OSError as exc:
                return 1, strip_controls(str(exc))
            os.close(slave_fd)
            slave_fd = -1
            stdin_fd = sys.stdin.fileno()
            stdout_fd = sys.stdout.fileno()
            while True:
                if _time.monotonic() - started > 300:
                    timed_out = True
                    proc.terminate()
                    break
                rlist = [master_fd]
                if proc.poll() is None:
                    rlist.append(stdin_fd)
                ready, _, _ = select.select(rlist, [], [], 0.05)
                if master_fd in ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break
                    captured.extend(chunk)
                    if len(captured) > max_buffer:
                        del captured[:len(captured) - MAX_OUTPUT_CHARS * 2]
                    os.write(stdout_fd, chunk)
                if stdin_fd in ready:
                    data = os.read(stdin_fd, 1024)
                    if data:
                        os.write(master_fd, data)
                if proc.poll() is not None and master_fd not in ready:
                    # Drain any remaining bytes after child exits.
                    while True:
                        r, _, _ = select.select([master_fd], [], [], 0.02)
                        if not r:
                            break
                        try:
                            chunk = os.read(master_fd, 4096)
                        except OSError:
                            chunk = b""
                        if not chunk:
                            break
                        captured.extend(chunk)
                        if len(captured) > max_buffer:
                            del captured[:len(captured) - MAX_OUTPUT_CHARS * 2]
                        os.write(stdout_fd, chunk)
                    break
            code = 124 if timed_out else proc.wait()
        finally:
            if slave_fd >= 0:
                os.close(slave_fd)
            os.close(master_fd)
            if old_tty is not None:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
        text = strip_controls(captured.decode("utf-8", errors="replace"))
        if timed_out:
            text = (text + "\n[command timed out after 300s]").strip()
        return code, text[-MAX_OUTPUT_CHARS:]

    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        return 124, strip_controls(partial + "\n[command timed out after 300s]")[-MAX_OUTPUT_CHARS:]
    except OSError as exc:
        return 1, strip_controls(str(exc))
    combined = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, strip_controls(combined)[-MAX_OUTPUT_CHARS:]
