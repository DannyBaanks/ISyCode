"""Workspace config access remains within explicit root-scoped owner grants."""
from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path

import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.approvals import ActionApprovalStore
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner
from isycode.workspace_config_owner import WorkspaceConfigOwner, _managed_ignore

pytestmark = pytest.mark.skipif(os.name == "nt", reason="descriptor-safe writes are POSIX-only")


@pytest.fixture
def config_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").touch()
    (root / ".isycode" / "commands").mkdir(parents=True)
    (root / ".isycode" / "config.json").write_text('{"version":1,"agent_steps":25}\n')
    (root / ".isycode" / "commands" / "review.md").write_text("Review safely.\n")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    return root, authority, approvals


def test_internal_config_read_uses_existing_workspace_read_grant(config_workspace):
    root, authority, _ = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    owner = LocalWorkspaceReadOwner(root, authority, owner_id="workspace_config")

    result = owner.execute("workspace.config.read", {"path": ".isycode/config.json"})

    assert result.decision == "ALLOW" and result.receipt is not None
    assert json.loads(result.text)["text"] == '{"version":1,"agent_steps":25}\n'


def test_generic_chat_read_still_cannot_read_internal_config(config_workspace):
    root, authority, _ = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])

    result = LocalWorkspaceReadOwner(root, authority).execute(
        "workspace.config.read", {"path": ".isycode/config.json"})

    assert result.decision == "DENY"
    assert "agent_steps" not in result.text


def test_internal_config_read_still_requires_an_explicit_read_grant(config_workspace):
    root, authority, _ = config_workspace

    result = LocalWorkspaceReadOwner(root, authority, owner_id="workspace_config").execute(
        "workspace.config.read", {"path": ".isycode/config.json"})

    assert result.decision == "DENY"
    assert result.receipt is None


def test_internal_config_write_requires_existing_write_grant_and_fresh_approval(config_workspace):
    root, authority, approvals = config_workspace
    owner = WorkspaceWriteOwner(root, authority, approvals, owner_id="workspace_config")
    preview = owner.preview(".isycode/config.json", '{"version":1,"agent_steps":50}\n')
    assert preview.request.action_id == "workspace.config.write"
    assert owner.apply(preview, None).decision == "DENY"
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])

    outcome = owner.apply(preview, approvals.issue(preview.request))

    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    assert (root / ".isycode" / "config.json").read_text() == '{"version":1,"agent_steps":50}\n'


def test_generic_file_writer_cannot_target_internal_config(config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    owner = WorkspaceWriteOwner(root, authority, approvals)

    with pytest.raises(ValueError, match="sensitive"):
        owner.preview(".isycode/config.json", "{}\n")


def test_internal_config_owner_rejects_symlinked_config_directory(config_workspace, tmp_path):
    root, authority, _ = config_workspace
    (root / ".isycode").rename(root / ".isycode-real")
    (root / ".isycode").symlink_to(root / ".isycode-real", target_is_directory=True)
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])

    result = LocalWorkspaceReadOwner(root, authority, owner_id="workspace_config").execute(
        "workspace.config.read", {"path": ".isycode/config.json"})

    assert result.decision == "DENY"
    assert result.receipt is None


def test_managed_ignore_appends_once_and_preserves_existing_newline_style():
    updated, error = _managed_ignore("*.pyc\r\n")
    assert not error and updated == "*.pyc\r\n" + (
        "# >>> ISYCODE managed block >>>\r\n.isycode/\r\n"
        "# <<< ISYCODE managed block <<<\r\n")
    assert _managed_ignore(updated) == (None, "")
    assert _managed_ignore(".isycode/\n")[0] is None


def test_malformed_managed_ignore_block_is_never_rewritten():
    result, error = _managed_ignore("# >>> ISYCODE managed block >>>\nother\n")
    assert result is None and "malformed" in error


def test_config_writer_enforces_path_specific_limits(config_workspace):
    root, authority, approvals = config_workspace
    owner = WorkspaceWriteOwner(root, authority, approvals, owner_id="workspace_config")
    with pytest.raises(ValueError, match="64 KiB"):
        owner.preview(".isycode/config.json", "x" * (64 * 1024 + 1))
    with pytest.raises(ValueError, match="32 KiB"):
        owner.preview(".isycode/commands/large.md", "x" * (32 * 1024 + 1))


def test_initialize_preflight_requires_existing_authority_grants(config_workspace):
    root, authority, approvals = config_workspace
    result = WorkspaceConfigOwner(root, authority, approvals).prepare_initialization()
    assert not result.previews
    assert "Cannot safely inspect workspace config" in result.message


def test_fallback_folder_never_loads_or_initializes_workspace_config(tmp_path):
    root = tmp_path / "fallback"
    root.mkdir()
    (root / ".isycode" / "config.json").parent.mkdir(parents=True)
    (root / ".isycode" / "config.json").write_text('{"version":1,"agent_steps":50}\n')
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    owner = WorkspaceConfigOwner(root, authority, ActionApprovalStore())

    assert owner.read_config() == (None, "workspace config requires this folder's own .isyroot marker")
    assert not owner.prepare_initialization().previews
    with pytest.raises(ValueError, match="requires this folder's own"):
        owner.preview_update({"agent_steps": 25})


def test_initialize_preflight_creates_reviewable_gitignore_and_config_previews(config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.list", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    authority.set_grant("git.status", enabled=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    # Existing valid config is preserved; only the ignore file needs a change.
    (root / ".isycode" / "config.json").write_text('{"version":1,"agent_steps":25}\n')
    result = WorkspaceConfigOwner(root, authority, approvals).prepare_initialization()
    assert len(result.previews) == 1
    assert result.previews[0].path == ".gitignore"
    assert ".isycode/" in result.previews[0].content
    assert not (root / ".gitignore").exists()


def test_non_git_workspace_proposes_config_but_does_not_claim_to_install_gitignore(
        config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    (root / ".isycode").rename(root / ".isycode-saved")
    result = WorkspaceConfigOwner(root, authority, approvals).prepare_initialization()
    assert [preview.path for preview in result.previews] == [".isycode/config.json"]
    assert "not a Git repository" in result.message


def test_initialization_creates_commands_directory_under_the_same_approved_write(config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    (root / ".isycode").rename(root / ".isycode-saved")
    owner = WorkspaceConfigOwner(root, authority, approvals)
    plan = owner.prepare_initialization()
    preview = plan.previews[0]
    assert preview.request.parameters["new_folders"] == (".isycode", ".isycode/commands")
    assert owner.apply(preview, approvals.issue(preview.request)).decision == "ALLOW"
    assert (root / ".isycode" / "commands").is_dir()


def test_initialize_refuses_config_already_tracked_by_git(config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    authority.set_grant("git.status", enabled=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "add", ".isycode/config.json"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-q", "-m", "track config"], cwd=root, check=True)
    result = WorkspaceConfigOwner(root, authority, approvals).prepare_initialization()
    assert not result.previews and "already contains tracked files" in result.message


def test_workspace_commands_are_read_by_the_config_owner(config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.list", enabled=True, path_prefixes=[root])
    commands, issue = WorkspaceConfigOwner(root, authority, approvals).commands()
    assert not issue
    assert commands["review"].template == "Review safely."
    assert commands["review"].source == "workspace"


def test_workspace_preference_update_is_previewed_and_approval_bound(config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    owner = WorkspaceConfigOwner(root, authority, approvals)
    preview = owner.preview_update({"agent_steps": 50})
    assert preview.path == ".isycode/config.json"
    assert owner.apply(preview, None).decision == "DENY"
    result = owner.apply(preview, approvals.issue(preview.request))
    assert result.decision == "ALLOW"
    assert json.loads((root / ".isycode/config.json").read_text())["agent_steps"] == 50


def test_legacy_command_migration_copies_reviewed_text_and_preserves_source(config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.list", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    source = root / ".isycode-commands" / "ship.md"
    source.parent.mkdir()
    source.write_text("Ship $ARGUMENTS\r\n")
    owner = WorkspaceConfigOwner(root, authority, approvals)

    assert owner.legacy_commands()[0] == ["ship"]
    preview = owner.preview_migrate_legacy("ship")
    assert preview.path == ".isycode/commands/ship.md"
    assert preview.content == "Ship $ARGUMENTS\r\n"
    assert owner.apply(preview, approvals.issue(preview.request)).decision == "ALLOW"
    assert source.read_bytes() == b"Ship $ARGUMENTS\r\n"
    assert (root / ".isycode/commands/ship.md").read_bytes() == source.read_bytes()


def test_legacy_command_migration_refuses_existing_destination(config_workspace):
    root, authority, approvals = config_workspace
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    (root / ".isycode-commands").mkdir()
    (root / ".isycode-commands" / "review.md").write_text("legacy")
    owner = WorkspaceConfigOwner(root, authority, approvals)
    with pytest.raises(ValueError, match="already exists"):
        owner.preview_migrate_legacy("review")
