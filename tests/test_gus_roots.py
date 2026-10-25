"""GUS's roots (ADR 0015): private settings, default target, exact grants, readiness."""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.gus_l0 import gus_turn
from isycode.gus_roots import (
    DEFAULT_SETTINGS, GusRoots, GusRootsError, GusSettingsStore, TARGET_GIT_ACTIONS,
    configure_target_grants, configured_target, running_checkout, validate_target,
)
from isycode.workspace_authority import WorkspaceAuthority, known_provider_hosts
from isycode.workspace_trust import QUIET_FLOW_ACTIONS, quiet_request
from isycode.workspace_write import WorkspaceWriteOwner
from test_gus_session import _checkout

REPO = Path(__file__).resolve().parents[1]


def _git(root, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root.parent)}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True,
                          capture_output=True, text=True).stdout


def _committed_target(root, branch="gus/fix-it"):
    _git(root, "init", "-q", "-b", branch)
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "core.eol", "lf")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-q", "-m", "base")
    return root


def _set_target(root):
    store = GusSettingsStore()
    data = store.read()
    data["target"] = str(root)
    store.write(data)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    return tmp_path


def test_settings_are_private_bounded_and_versioned(state):
    store = GusSettingsStore()
    data = store.read()
    assert data["version"] == 1
    assert data["read_scope"] == {"mode": "machine", "folders": []}
    assert data["target"] is None and data["memory_mode"] == "explicit"
    store.write(data)
    if os.name == "posix":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600

        os.chmod(store.path, 0o644)                # a readable-by-others file is refused
        with pytest.raises(GusRootsError, match="private"):
            store.read()
        os.chmod(store.path, 0o600)
    else:
        from isycode.platform_storage import storage
        assert storage.private(store.directory)    # Windows privacy is the folder's ACL

    store.path.write_text(json.dumps({**data, "read_scope": {
        "mode": "folders", "folders": ["/tmp"] * 65}}), encoding="utf-8")
    with pytest.raises(GusRootsError, match="folders"):
        store.read()

    store.path.write_text(" " * (64 * 1024 + 1), encoding="utf-8")
    with pytest.raises(GusRootsError, match="bounded regular"):
        store.read()

    store.path.unlink()
    store.path.symlink_to(state / "elsewhere.json")
    with pytest.raises(GusRootsError, match="bounded regular"):
        store.read()


def test_consent_is_bound_to_the_read_scope(state):
    store = GusSettingsStore()
    data = store.consent(store.read(), at="2026-10-24T00:00:00+00:00")
    assert store.consented(data)
    assert not store.consented({**data, "read_scope": {"mode": "home", "folders": []}})
    assert not store.consented({**data, "read_scope": {
        "mode": "folders", "folders": [str(state)]}})
    assert store.consented({**data, "memory_mode": "automatic"})


def test_the_default_target_is_the_running_checkout(state, tmp_path):
    running = running_checkout()
    assert running is not None and running == REPO
    assert configured_target(DEFAULT_SETTINGS) == running

    saved = _checkout(tmp_path / "saved")
    assert configured_target({**DEFAULT_SETTINGS, "target": str(saved)}) == saved.resolve()
    assert configured_target({**DEFAULT_SETTINGS,
                              "target": str(tmp_path / "gone")}) == running

    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(GusRootsError, match="not an ISyCode checkout"):
        validate_target(str(plain))
    with pytest.raises(GusRootsError, match="does not exist"):
        validate_target(str(tmp_path / "gone"))


def test_the_target_grants_are_explicit_and_narrow(state, tmp_path):
    target = _committed_target(_checkout(tmp_path / "isycode"))
    _set_target(target)
    roots = GusRoots(target)
    authority = roots.authority()
    policy = authority.policy()
    assert authority.gus_target is True
    assert policy["mode"] == "security"

    from isycode.command_runner import sandbox_executable
    expected = (QUIET_FLOW_ACTIONS - {"workspace.command.run"}) | TARGET_GIT_ACTIONS
    if sandbox_executable():
        expected |= {"workspace.command.run"}
    assert set(policy["grants"]) == expected

    for action in QUIET_FLOW_ACTIONS - {"workspace.command.run"}:
        grant = policy["grants"][action]
        assert grant["enabled"] is True
        assert grant["path_prefixes"] == [str(target.resolve())]
    if sandbox_executable():
        assert policy["grants"]["workspace.command.run"]["executables"] == [
            sandbox_executable()]
    for action in TARGET_GIT_ACTIONS:
        assert policy["grants"][action]["enabled"] is True
        assert "path_prefixes" not in policy["grants"][action]

    # Never sessions, workspace memory, credentials, provider calls or pushes.
    for forbidden in ("session.create", "session.resume", "workspace.memory.read",
                      "workspace.memory.write", "workspace.memory.forget",
                      "credentials.add", "credentials.use", "credentials.revoke",
                      "provider.request", "git.push"):
        assert forbidden not in policy["grants"]

    provider = roots.provider_authority()
    provider_policy = provider.policy()
    assert provider.root == roots.settings.directory.parent
    assert provider_policy["mode"] == "security"
    assert set(provider_policy["grants"]) == {"provider.request"}
    assert provider_policy["grants"]["provider.request"]["network_hosts"] \
        == known_provider_hosts()


def test_a_dirty_worktree_blocks_tools(state, tmp_path, monkeypatch):
    target = _committed_target(_checkout(tmp_path / "isycode"))
    _set_target(target)
    roots = GusRoots(target)
    assert roots.target_ready() == (True, "")
    (target / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
    ready, reason = roots.target_ready()
    assert not ready and "clean checkout" in reason

    monkeypatch.setattr("isycode.gus_roots.running_checkout", lambda: None)
    plain = tmp_path / "plain"
    plain.mkdir()
    no_target = GusRoots(plain, data={**DEFAULT_SETTINGS, "target": None})
    assert no_target.target is None
    assert no_target.target_ready() == (False, "GUS has no configured ISyCode checkout to edit")
    with pytest.raises(GusRootsError, match="no editable"):
        no_target.authority()


def test_quiet_gus_accepts_its_target_authority_only_inside_a_turn(state, tmp_path):
    target = _committed_target(_checkout(tmp_path / "isycode"))
    _set_target(target)
    roots = GusRoots(target)
    authority = roots.authority()
    request = WorkspaceWriteOwner(target, authority, ActionApprovalStore()).preview(
        "notes/x.txt", "hello\n").request

    assert not quiet_request(authority, request)   # outside a GUS turn it asks
    with gus_turn(target):
        assert quiet_request(authority, request)

    plain = WorkspaceAuthority(target, state_directory=state / "state" / "plain-authority")
    configure_target_grants(plain, target)          # same grants, but not a GUS target
    assert not getattr(plain, "gus_target", False)
    with gus_turn(target):
        assert not quiet_request(plain, request)
