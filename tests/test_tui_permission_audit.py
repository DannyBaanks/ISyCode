"""Tests for remediation of TUI permission audit findings."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from isycode.localization import configure_locale, tr
from isycode.tui_app_authority import AuthorityMixin
from isycode.tui_screens_approval import ApprovalScreen, LocalMCPConfirmScreen, TailscaleConfirmScreen
from isycode.workspace_authority import WorkspaceAuthority


def test_spanish_structural_summary_labels_and_values():
    configure_locale("es")
    screen = ApprovalScreen()
    widget = screen._structural_summary(
        owner="workspace authority",
        scope="/workspace",
        duration="persistent workspace grant",
        not_granted="sensitive files, .isyroot, and unapproved folder writes stay off-limits",
    )
    rendered = widget._Static__content.plain

    assert "Propietario: autoridad del espacio de trabajo" in rendered
    assert "Alcance: /workspace" in rendered
    assert "Duración: permiso persistente del espacio de trabajo" in rendered
    assert "Exclusiones: archivos sensibles, .isyroot y carpetas no aprobadas quedan fuera de límites" in rendered
    assert "Owner:" not in rendered
    assert "Scope:" not in rendered
    assert "Duration:" not in rendered
    assert "Not granted:" not in rendered


def test_tailscale_confirm_screen_supports_custom_structural_summary():
    screen = TailscaleConfirmScreen(
        "Allow file edits in this workspace?",
        "Details...",
        "Allow edits",
        owner="workspace authority",
        scope="/test/workspace",
        duration="persistent workspace grant",
        not_granted="sensitive files stay off-limits",
    )
    assert screen.owner == "workspace authority"
    assert screen.scope == "/test/workspace"
    assert screen.duration == "persistent workspace grant"
    assert screen.not_granted == "sensitive files stay off-limits"


def test_local_mcp_confirm_does_not_promise_unapplied_filesystem_restriction():
    screen = LocalMCPConfirmScreen(
        "Start MCP server · test",
        "Runs with user permissions...",
        "python3 server.py",
        "Start server",
    )
    assert "no filesystem access" not in screen.not_granted.lower()
    assert "user permissions" in screen.not_granted.lower()


@pytest.mark.asyncio
async def test_session_delete_grant_does_not_reactivate_previous_session(tmp_path):
    class FakeApp(AuthorityMixin):
        def __init__(self, root: Path):
            self._workspace_root = root
            self._active_chat_session_id = None
            self.menu_opened = False
            self.appended = []

        def _append(self, text, color=None):
            self.appended.append(text)

        def _open_authority_menu(self):
            self.menu_opened = True

        async def _await_screen(self, screen):
            return True

    root = tmp_path / "workspace"
    root.mkdir()
    app = FakeApp(root)
    authority = WorkspaceAuthority(root)

    # 1. Authorize session A
    app._active_chat_session_id = "session-A"
    await app._change_session_delete_grant(enabled=True)
    policy = authority.policy()
    assert policy["grants"]["session.delete"]["enabled"] is True
    assert policy["grants"]["session.delete"]["targets"] == ["session-A"]

    # 2. Disable session A
    await app._change_session_delete_grant(enabled=False)
    policy = authority.policy()
    assert policy["grants"]["session.delete"]["enabled"] is False
    assert "session-A" not in policy["grants"]["session.delete"].get("targets", [])

    # 3. Authorize session B
    app._active_chat_session_id = "session-B"
    await app._change_session_delete_grant(enabled=True)
    policy = authority.policy()
    assert policy["grants"]["session.delete"]["enabled"] is True
    assert policy["grants"]["session.delete"]["targets"] == ["session-B"]
    # Verify session A is NOT reactivated
    assert "session-A" not in policy["grants"]["session.delete"]["targets"]
