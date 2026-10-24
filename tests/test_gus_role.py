"""GUS role (ADR 0011, MK1): a declared role that is checked on load and grants nothing."""
from pathlib import Path

import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.gus_role import (
    GUS_ACTION_CEILING, GusRoleError, load_gus_role, parse_role_document)
from isycode.workspace_authority import WorkspaceAuthority

ROLE = (Path(__file__).resolve().parents[1] / "src" / "isycode" / "agents" / "gus.md").read_text(
    encoding="utf-8")


def _with_actions(*extra: str) -> str:
    """The shipped role document with more action lines appended to its list."""
    head, separator, body = ROLE.partition("\n---\n")
    return head + "".join(f"\n  - {action}" for action in extra) + separator + body


def test_the_shipped_role_loads_inside_the_adr_ceiling():
    role = load_gus_role()
    assert (role.id, role.name, role.mode) == ("gus", "GUS", "maintainer")
    assert role.actions <= GUS_ACTION_CEILING
    assert "workspace.files.write" in role.actions and "workspace.command.run" in role.actions
    assert "gus/<topic>" in role.instructions


def test_the_ceiling_is_pinned_to_adr_0011_and_0015():
    assert GUS_ACTION_CEILING == {
        "workspace.files.list", "workspace.files.read", "workspace.files.search",
        "workspace.context.inject", "workspace.files.write", "workspace.files.restore",
        "workspace.files.delete", "workspace.files.move", "workspace.command.run",
        "workspace.turn.undo", "git.status", "git.diff", "git.commit",
        "machine.files.list", "machine.files.read", "machine.files.search",
        "machine.files.grep", "gus.memory.write"}


@pytest.mark.parametrize("action", [
    "git.push", "credentials.use", "credentials.add", "provider.request",
    "workspace.config.write", "workspace.files.read_sensitive", "web.fetch",
    "mcp.invoke", "l1.activate", "l1.create", "role.select", "bridge.send",
])
def test_a_role_that_asks_for_more_does_not_load(action):
    with pytest.raises(GusRoleError, match="beyond what ADR 0011 allows"):
        parse_role_document(_with_actions(action))


@pytest.mark.parametrize("document, reason", [
    (_with_actions("workspace.files.teleport"), "unknown actions"),
    (_with_actions("git.diff"), "declared twice"),
    (ROLE.replace("id: gus", "id: keeper", 1), "id must be 'gus'"),
    (ROLE.replace("name: GUS", "name: Root", 1), "name must be 'GUS'"),
    (ROLE.replace("mode: maintainer", "mode: primary", 1), "mode must be 'maintainer'"),
    (ROLE.replace("mode: maintainer", "mode: maintainer\nauthority: full", 1), "extra"),
    (ROLE.replace("mode: maintainer\n", "", 1), "missing"),
    (ROLE.replace("actions:\n", "actions: git.push\n", 1), "must be a list"),
    (ROLE.partition("\n---\n")[0] + "\n---\n   \n", "no instructions"),
    (ROLE.split("---", 2)[2], "frontmatter block"),
    (ROLE + "x" * (32 * 1024), "larger than 32 KiB"),
])
def test_a_malformed_role_does_not_load(document, reason):
    with pytest.raises(GusRoleError, match=reason):
        parse_role_document(document)


def test_loading_the_role_grants_nothing(tmp_path, monkeypatch):
    """GK1-02: Sentinel decides the same with and without the role loaded."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("security")
    policy = authority.effective_policy()

    def read():
        return LocalWorkspaceReadOwner(root.resolve(), authority).execute(
            "workspace.files.read", {"path": "app.py"}).decision

    before = read()
    role = load_gus_role()
    assert "workspace.files.read" in role.actions
    assert read() == before == "DENY"
    assert authority.effective_policy() == policy
    assert authority.mode() == "security"


def test_the_role_document_ships_with_the_package():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"agents/*.md"' in pyproject
