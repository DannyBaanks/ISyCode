"""Workspace preferences change product defaults without changing authority."""
import os
import asyncio
import subprocess

import pytest
from test_daily_tui import configure
from isycode.tui import TUIApp
from isycode.action_audit import ActionAuditJournal
from isycode.workspace_authority import WorkspaceAuthority

pytestmark = pytest.mark.skipif(os.name == "nt", reason="workspace owner probes are POSIX-only")


def test_tui_uses_authorized_workspace_preferences(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    (tmp_path / ".isyroot").touch()
    config = tmp_path / ".isycode" / "config.json"
    config.parent.mkdir()
    config.write_text('{"version":1,"agent_steps":50,"answer_tokens":4096,'
                      '"chat_token_budget":10000}\n')

    from isycode.tui import TUIApp
    from isycode.workspace_authority import WorkspaceAuthority

    authority = WorkspaceAuthority(tmp_path)
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[tmp_path])
    app = TUIApp()

    assert app._workspace_preference_values() == {
        "agent_steps": 50, "answer_tokens": 4096, "chat_token_budget": 10000}
    assert ActionAuditJournal(tmp_path).verify().receipts >= 1


def test_tui_ignores_workspace_preferences_without_read_authority(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    (tmp_path / ".isyroot").touch()
    config = tmp_path / ".isycode" / "config.json"
    config.parent.mkdir()
    config.write_text('{"version":1,"agent_steps":50,"chat_token_budget":10000}\n')

    from isycode.tui import TUIApp

    app = TUIApp()
    assert app._workspace_preference_values() == {}
    assert "unavailable" in app._workspace_config_warning


def test_persistent_workspace_settings_are_hidden_without_own_marker(tmp_path, monkeypatch, capsys):
    root = configure(tmp_path, monkeypatch)
    (root / ".isyroot").unlink(missing_ok=True)

    async def scenario():
        fallback = TUIApp()
        async with fallback.run_test() as pilot:
            await pilot.pause()
            fallback._open_settings_menu()
            assert not {"workspace_config_init", "workspace_config_preferences",
                        "workspace_config_migrate"} & {
                entry["kind"] for entry in fallback._menu_entries
            }

        (root / ".isyroot").write_bytes(b"")
        marked = TUIApp()
        async with marked.run_test() as pilot:
            await pilot.pause()
            marked._open_settings_menu()
            assert {"workspace_config_init", "workspace_config_preferences",
                    "workspace_config_migrate"} <= {
                entry["kind"] for entry in marked._menu_entries
            }

    with capsys.disabled():
        asyncio.run(scenario())


@pytest.mark.parametrize("approve_write", [True, False], ids=["approved", "cancelled"])
def test_initialization_flow_uses_reviewed_workspace_writes(
        tmp_path, monkeypatch, capsys, approve_write):
    root = configure(tmp_path, monkeypatch)
    (root / ".isyroot").write_bytes(b"")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    authority = WorkspaceAuthority(root)
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    authority.set_grant("git.status", enabled=True)

    reviewed = []

    async def approve(_self, screen):
        reviewed.append(screen.preview.path)
        return approve_write

    monkeypatch.setattr(TUIApp, "_await_screen", approve)

    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._initialize_workspace_config()
            if approve_write:
                assert (root / ".isycode" / "commands").is_dir()
                assert (root / ".isycode" / "config.json").read_text(encoding="utf-8") == '{"version":1}\n'
                ignore = (root / ".gitignore").read_text(encoding="utf-8")
                assert ".isycode/" in ignore
                subprocess.run(["git", "check-ignore", "-q", ".isycode/config.json"],
                               cwd=root, check=True)
                assert reviewed == [".gitignore", ".isycode/config.json"]
                assert ActionAuditJournal(root).verify().receipts >= 2
            else:
                assert reviewed == [".gitignore"]
                assert not (root / ".gitignore").exists()
                assert not (root / ".isycode").exists()

    with capsys.disabled():
        asyncio.run(scenario())
