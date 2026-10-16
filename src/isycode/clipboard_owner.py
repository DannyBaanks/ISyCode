"""Copy an explicitly chosen text range, complete box or file path.

``clipboard.copy`` runs only from a user gesture in the TUI — Ctrl+C on a selection, a copy-menu choice, or the Copy path button — never from a model tool. It
needs a ``clipboard.copy`` grant for the ``clipboard`` target and passes
IsySentinel like every other effect. Requests and receipts carry only the
source, size and a digest; the copied text never enters the journal.

The terminal escape sequence (OSC 52) is not supported by every terminal
(GNOME Terminal ignores it), so the system clipboard tool is tried first:
wl-copy on Wayland, xclip or xsel on X11, pbcopy on macOS, clip on Windows.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

OWNER_ID = "clipboard"
CLIPBOARD_TARGET = "clipboard"
CLIPBOARD_SOURCES = frozenset({"selection", "file_path", "content_box"})
MAX_COPY_BYTES = 1024 * 1024
TOOL_TIMEOUT_S = 3


from isycode.platform_clipboard import (system_clipboard_command, read_system_clipboard, encode_text)


class ClipboardOwner:
    """The only execution owner for clipboard.copy."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 command_finder: Callable[[], list[str] | None] = system_clipboard_command):
        self.root = root.resolve(strict=True)
        self.gate = ProductActionGate(self.root, authority, owner_id=OWNER_ID)
        self._command_finder = command_finder

    def paste(self) -> tuple[ActionOutcome, str, bytes]:
        """Authorize before probing or reading the OS clipboard; never journal bytes."""
        request = ActionRequest("clipboard.paste", self.root, CLIPBOARD_TARGET,
                                {"source": "user_paste", "max_bytes": 8 * 1024 * 1024}, execution_owner="clipboard")
        _, decision = self.gate.authorize(request)
        if not decision.allowed:
            return ActionOutcome("Nothing pasted.", "DENY", None, "; ".join(c.reason for c in decision.checks if not c.passed)), "", b""
        try:
            mime, data = read_system_clipboard()
        except (OSError, ValueError, subprocess.SubprocessError):
            return ActionOutcome("Nothing pasted.", "ERROR", None, "clipboard unavailable, unsupported, too large or timed out"), "", b""
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
                                "ALLOW", "SUCCESS", hashlib.sha256(data).hexdigest())
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Nothing pasted.", "NOT_VERIFIABLE", None, "durable action journal unavailable"), "", b""
        return ActionOutcome(mime, "ALLOW", receipt, "clipboard read"), mime, data

    def copy(self, text: str, *, source: str,
             terminal_write: Callable[[str], None] | None = None) -> ActionOutcome:
        if not isinstance(text, str) or not text or source not in CLIPBOARD_SOURCES:
            return ActionOutcome("Nothing copied.", "DENY", None, "nothing to copy")
        data = text.encode("utf-8")
        if len(data) > MAX_COPY_BYTES:
            return ActionOutcome("Nothing copied.", "DENY", None, "selection exceeds 1 MiB")
        request = ActionRequest(
            "clipboard.copy", self.root, CLIPBOARD_TARGET,
            {"source": source, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
            execution_owner="clipboard")
        _, decision = self.gate.authorize(request)
        if not decision.allowed:
            return ActionOutcome("Nothing copied.", "DENY", None,
                                 "; ".join(check.reason for check in decision.checks if not check.passed))
        method = "terminal"
        command = self._command_finder()
        if command:
            try:
                subprocess.run(command, input=encode_text(text), stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=TOOL_TIMEOUT_S, check=True)
                method = Path(command[0]).name
            except (OSError, subprocess.SubprocessError):
                command = None
        if terminal_write is not None:
            terminal_write(text)  # OSC 52 as well, for terminals that support it
        if not command and terminal_write is None:
            return ActionOutcome("Nothing copied.", "ERROR", None, "no clipboard is available")
        result = f"{source}:{len(data)}:{method}"
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), "clipboard.copy", request.digest,
                                "ALLOW", "SUCCESS", hashlib.sha256(result.encode()).hexdigest())
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Copied, but the receipt could not be journaled.", "NOT_VERIFIABLE",
                                 None, "durable action journal is unavailable")
        return ActionOutcome(method, "ALLOW", receipt, f"copied {len(text)} characters")


__all__ = ["CLIPBOARD_TARGET", "ClipboardOwner", "MAX_COPY_BYTES", "system_clipboard_command"]
