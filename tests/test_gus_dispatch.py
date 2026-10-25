"""GUS's tool dispatch (ADR 0015): target-bound, quiet only in a turn, commit asks, L0 refused."""
import asyncio
import json
import os
import subprocess

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.git_owner import git_executable
from isycode.gus_dispatch import GusToolDispatcher
from isycode.gus_l0 import gus_turn
from isycode.gus_roots import GusRoots, GusSettingsStore
from test_gus_session import _checkout


def _git(root, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root.parent)}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True,
                          capture_output=True, text=True).stdout


def _committed_repo(root, branch="gus/fix-it"):
    _git(root, "init", "-q", "-b", branch)
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "core.eol", "lf")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-q", "-m", "base")
    return root


def _call(name, call_id="call_1", **arguments):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def _ask(seen, answer=True):
    async def approve(kind, preview):
        seen.append((kind, preview))
        return answer
    return approve


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    visible = tmp_path / "visible"
    visible.mkdir()
    (visible / "note.txt").write_text("visible\n", encoding="utf-8")
    target = _committed_repo(_checkout(tmp_path / "isycode"))
    store = GusSettingsStore()
    data = store.read()
    store.write({**data, "target": str(target)})
    return visible, target, GusRoots(visible)


def test_a_write_inside_the_target_is_applied_quietly(world):
    _, target, roots = world
    asked = []
    dispatcher = GusToolDispatcher(roots, ActionApprovalStore(), approve=_ask(asked))
    with gus_turn(target):
        call_id, output = asyncio.run(dispatcher(
            _call("workspace_write", path="notes/x.txt", content="hello\n")))
    result = json.loads(output)
    assert call_id == "call_1"
    assert result["status"] == "done" and result["receipt"].startswith("rcpt_")
    assert (target / "notes" / "x.txt").read_text(encoding="utf-8") == "hello\n"
    assert asked == []                                # quiet inside its own turn


@pytest.mark.parametrize("path", ["../visible/note.txt", "/tmp/absolute.txt", "link/note.txt"])
def test_a_write_outside_the_target_is_refused(world, path):
    visible, target, roots = world
    if path.startswith("link/"):
        (target / "link").symlink_to(visible, target_is_directory=True)
    dispatcher = GusToolDispatcher(roots, ActionApprovalStore(), approve=_ask([], True))
    with gus_turn(target):
        _, output = asyncio.run(dispatcher(
            _call("workspace_write", path=path, content="escaped\n")))
    result = json.loads(output)
    assert result["error"] == "ISyCode denied the call"
    assert (visible / "note.txt").read_text(encoding="utf-8") == "visible\n"


def test_l0_is_refused_even_inside_a_turn(world):
    _, target, roots = world
    before = (target / "AGENTS.md").read_text(encoding="utf-8")
    dispatcher = GusToolDispatcher(roots, ActionApprovalStore(), approve=_ask([], True))
    with gus_turn(target):
        _, output = asyncio.run(dispatcher(
            _call("workspace_write", path="AGENTS.md", content="weakened\n")))
    result = json.loads(output)
    assert result["error"] == "ISyCode denied the call"
    assert "L0" in result["reason"]
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == before


@pytest.mark.skipif(git_executable() is None, reason="git is not installed")
def test_a_commit_always_asks_the_person(world):
    _, target, roots = world
    quiet = GusToolDispatcher(roots, ActionApprovalStore(), approve=_ask([], True))
    with gus_turn(target):
        _, written = asyncio.run(
            quiet(_call("workspace_write", path="notes/x.txt", content="hello\n")))
    assert json.loads(written)["status"] == "done", written

    asked = []
    refusing = GusToolDispatcher(roots, ActionApprovalStore(), approve=_ask(asked, False))
    with gus_turn(target):
        _, output = asyncio.run(refusing(_call("git_commit", message="gus: add notes")))
    assert json.loads(output)["status"] == "rejected_by_user", output
    assert [kind for kind, _ in asked] == ["commit"]
    assert _git(target, "log", "-1", "--format=%s").strip() == "base"

    accepting = GusToolDispatcher(roots, ActionApprovalStore(), approve=_ask([], True))
    with gus_turn(target):
        _, output = asyncio.run(accepting(_call("git_commit", message="gus: add notes")))
    result = json.loads(output)
    assert result.get("message") == "gus: add notes" and result.get("paths") == ["notes/x.txt"], output
    assert len(result["commit"]) == 40
    assert _git(target, "log", "-1", "--format=%s").strip() == "gus: add notes"


def test_a_command_needs_the_sandbox(world, monkeypatch):
    _, target, roots = world
    monkeypatch.setattr("isycode.command_runner.sandbox_executable", lambda: None)
    dispatcher = GusToolDispatcher(roots, ActionApprovalStore(), approve=_ask([], True))
    with gus_turn(target):
        _, output = asyncio.run(dispatcher(
            _call("workspace_run", argv=["echo", "hi"])))
    result = json.loads(output)
    assert result["error"] == "ISyCode denied the call"
    assert "sandbox" in result["reason"].casefold()
