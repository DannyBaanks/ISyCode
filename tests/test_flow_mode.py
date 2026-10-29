"""GF-01: Flow skips the per-action question for recoverable local work only.

The matrix compares Security, Classic without trust, trusted Classic and Flow
on the same kernel: the same owners, grants, IsySentinel and ledger decide.
"""
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner
from isycode.effect_policy import implicit_actions
from isycode.headless import available_tools
from isycode.security import ActionRequest
from isycode.workspace_authority import MODES, WorkspaceAuthority
from isycode.workspace_trust import (
    ACCEPT_PHRASE, QUIET_FLOW_ACTIONS, WorkspaceTrust, modal_required, quiet_classic,
    quiet_flow, quiet_request,
)
from isycode.workspace_write import WorkspaceWriteOwner

_COMMANDS = importlib.util.spec_from_file_location(
    "isycode_flow_command_tests", Path(__file__).with_name("test_command_runner.py"))
_COMMAND_MODULE = importlib.util.module_from_spec(_COMMANDS)
_COMMANDS.loader.exec_module(_COMMAND_MODULE)
FAKE_BWRAP = _COMMAND_MODULE.FAKE_BWRAP

PROFILES = ("security", "classic", "classic-trusted", "flow")


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "isycode-state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("", encoding="utf-8")
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / "old.txt").write_text("old\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("classic")
    return authority, root.resolve()


def _profile(authority, profile: str) -> None:
    if profile == "classic-trusted":
        authority.set_mode("classic")
        WorkspaceTrust().accept(authority, ACCEPT_PHRASE)
    else:
        authority.set_mode(profile)


def _fake_sandbox(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "bwrap"
    fake.write_text(FAKE_BWRAP.format(python=Path(sys.executable).resolve(),
                                      log=str(tmp_path / "bwrap.json")), encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def test_flow_is_a_mode_with_the_classic_preset_including_turn_undo():
    assert MODES == {"security", "classic", "flow"}
    # Flow shares Classic's preset. Undoing a whole turn is in both since ADR 0013
    # (a GUS turn is recorded in any mode); only Flow undoes without asking.
    assert implicit_actions("flow") == implicit_actions("classic")
    assert "workspace.turn.undo" in implicit_actions("classic")
    assert implicit_actions("security") == frozenset()


@pytest.mark.parametrize("profile", PROFILES)
def test_recoverable_local_work_by_profile(project, profile):
    authority, root = project
    _profile(authority, profile)
    approvals = ActionApprovalStore()
    reader = LocalWorkspaceReadOwner(root, authority)
    writer = WorkspaceWriteOwner(root, authority, approvals)

    read = reader.execute("workspace.files.read", {"path": "app.py"})
    write = writer.apply(writer.preview("app.py", "x = 2\n"), None)
    delete = writer.apply(writer.preview_delete("old.txt"), None)

    quiet = profile in {"classic-trusted", "flow"}
    assert (read.decision == "ALLOW") is (profile != "security")
    assert (write.decision == "ALLOW") is quiet, write.reason
    assert (delete.decision == "ALLOW") is quiet, delete.reason
    assert (root / "app.py").read_text(encoding="utf-8") == ("x = 2\n" if quiet else "x = 1\n")
    assert (root / "old.txt").exists() is not quiet


@pytest.mark.skipif(os.name != "posix", reason="the fake sandbox is a POSIX script")
@pytest.mark.parametrize("profile", PROFILES)
def test_sandboxed_commands_by_profile(project, tmp_path, monkeypatch, profile):
    authority, root = project
    _fake_sandbox(tmp_path, monkeypatch)
    _profile(authority, profile)
    runner = CommandRunOwner(root, authority, ActionApprovalStore())
    preview = runner.prepare(["echo", "flow-command"])
    outcome = asyncio.run(runner.run(preview, None))
    quiet = profile in {"classic-trusted", "flow"}
    assert (outcome.decision == "ALLOW") is quiet, outcome.reason
    if quiet:
        assert "flow-command" in json.loads(outcome.text)["output"]
    assert modal_required(authority, preview.request) is not quiet


def _boundary_requests(root: Path) -> dict[str, ActionRequest]:
    return {
        "commit": ActionRequest("git.commit", root, str(root), {"message": "x"}, execution_owner="git"),
        "push": ActionRequest("git.publish", root, "origin", {"remote": "origin"}, execution_owner="git"),
        "credential": ActionRequest("credentials.add", root, "openai", {"service": "openai"},
                                    execution_owner="credential_add"),
        "secret": ActionRequest("workspace.files.read_sensitive", root, str(root / ".env"),
                                {"path": ".env"}, execution_owner="workspace_read"),
        # The chat to a known provider is granted in Classic too; an unknown host is not.
        "provider": ActionRequest("provider.request", root, "exfil.example.invalid",
                                  {"host": "exfil.example.invalid"}, execution_owner="provider_network"),
        "config": ActionRequest("workspace.config.write", root, str(root / ".isycode/config.json"),
                                {"path": ".isycode/config.json"}, execution_owner="workspace_config"),
        "mcp": ActionRequest("mcp.invoke", root, "server", {"tool": "x"}, execution_owner="mcp"),
        "big-stage": ActionRequest("workspace.command.run", root, "/usr/bin/echo",
                                   {"argv": ["echo"], "max_stage_bytes": 2 ** 33},
                                   execution_owner="workspace_command"),
    }


def test_flow_keeps_every_other_boundary(project):
    authority, root = project
    authority.set_mode("flow")
    approvals = ActionApprovalStore()
    for name, request in _boundary_requests(root).items():
        assert not quiet_flow(authority, request), name
        assert not quiet_request(authority, request), name
        decision = authority.evaluate(request, approvals=approvals, approval=None)
        assert not decision.allowed, (name, decision.reason)


def test_quiet_flow_list_is_the_recoverable_local_list():
    assert QUIET_FLOW_ACTIONS == {
        "workspace.files.list", "workspace.files.read", "workspace.files.search",
        "workspace.context.inject", "workspace.files.write", "workspace.files.restore",
        "workspace.files.delete", "workspace.files.move", "workspace.command.run",
        "workspace.turn.undo",
    }


def test_an_explicit_denial_wins_over_flow(project):
    authority, root = project
    authority.set_mode("flow")
    authority.set_grant("workspace.files.write", enabled=False)
    writer = WorkspaceWriteOwner(root, authority, ActionApprovalStore())
    assert writer.apply(writer.preview("app.py", "x = 9\n"), None).decision == "DENY"
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 1\n"


def test_flow_does_not_need_or_use_the_classic_trust_record(project):
    authority, root = project
    authority.set_mode("flow")
    request = WorkspaceWriteOwner(root, authority, ActionApprovalStore()).preview(
        "app.py", "x = 3\n").request
    assert not WorkspaceTrust().trusted(authority)
    assert quiet_flow(authority, request) and not quiet_classic(authority, request)
    with pytest.raises(ValueError):
        WorkspaceTrust().accept(authority, ACCEPT_PHRASE)   # trust is a Classic record


def test_flow_in_a_broad_folder_asks_again(project, monkeypatch):
    authority, root = project
    authority.set_mode("flow")
    monkeypatch.setattr("isycode.workspace_trust.broad_workspace_reason", lambda _root: "home folder")
    writer = WorkspaceWriteOwner(root, authority, ActionApprovalStore())
    preview = writer.preview("app.py", "x = 4\n")
    assert modal_required(authority, preview.request)
    assert writer.apply(preview, None).decision == "DENY"


def test_flow_without_a_sandbox_runs_no_command(project, monkeypatch):
    authority, root = project
    authority.set_mode("flow")
    monkeypatch.setattr("isycode.command_runner.sandbox_executable", lambda: None)
    with pytest.raises(ValueError, match="no unsandboxed fallback"):
        CommandRunOwner(root, authority, ActionApprovalStore()).prepare(["echo", "nope"])
    command = ActionRequest("workspace.command.run", root, "/usr/bin/echo", {"argv": ["echo"]},
                            execution_owner="workspace_command")
    assert not quiet_flow(authority, command)


def test_leaving_flow_brings_the_questions_back_at_once(project):
    authority, root = project
    authority.set_mode("flow")
    writer = WorkspaceWriteOwner(root, authority, ActionApprovalStore())
    assert writer.apply(writer.preview("app.py", "x = 5\n"), None).decision == "ALLOW"
    authority.set_mode("classic")
    assert writer.apply(writer.preview("app.py", "x = 6\n"), None).decision == "DENY"
    authority.set_mode("security")
    assert writer.apply(writer.preview("app.py", "x = 7\n"), None).decision == "DENY"
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 5\n"


def test_headless_offers_the_same_read_only_tools_in_flow(project):
    authority, root = project
    authority.set_mode("classic")
    classic = [item["function"]["name"] for item in available_tools(root, authority)]
    authority.set_mode("flow")
    flow = [item["function"]["name"] for item in available_tools(root, authority)]
    assert flow == classic
    assert not any(token in name for name in flow for token in ("write", "edit", "command", "commit"))


def test_an_older_reader_rejects_a_flow_policy(project, monkeypatch):
    """Rollback fails closed: a build without Flow does not read it as Classic."""
    authority, root = project
    authority.set_mode("flow")
    monkeypatch.setattr("isycode.workspace_authority.MODES", frozenset({"security", "classic"}))
    with pytest.raises(Exception):
        authority.policy()


def test_flow_tells_the_model_about_the_shell_and_nothing_else_changes():
    from isycode.command_runner import COMMAND_TOOL, command_tool

    flow = command_tool("flow")
    assert command_tool("classic") is COMMAND_TOOL and command_tool("security") is COMMAND_TOOL
    assert flow["function"]["parameters"] == COMMAND_TOOL["function"]["parameters"]
    assert flow["function"]["name"] == COMMAND_TOOL["function"]["name"]
    assert "bash" in flow["function"]["description"]
    assert "There is no shell" in COMMAND_TOOL["function"]["description"]


def test_real_flow_sandbox_keeps_host_environment_secrets_and_paths_out(project, tmp_path, monkeypatch):
    import socket
    from isycode.command_runner import sandbox_executable
    if sandbox_executable() is None:
        pytest.skip('a verified native sandbox is not available on this platform')
    authority, root = project
    authority.set_mode('flow')
    outside = tmp_path / 'outside.txt'
    outside.write_text('human outside\n')
    (root / '.env').write_text('FLOW_TEST_SECRET=must-stay-hidden\n')
    monkeypatch.setenv('FLOW_HOST_SECRET', 'host-environment-canary')
    if os.name == 'posix':
        (root / 'linked.txt').symlink_to(outside)
        os.link(outside, root / 'hardlinked.txt')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]
    code = f'''import os,socket,pathlib,json
assert 'FLOW_HOST_SECRET' not in os.environ
assert b'host-environment-canary' not in pathlib.Path('/proc/1/environ').read_bytes()
for name in ('.env', 'linked.txt', 'hardlinked.txt', {str(outside)!r}):
    try:
        data = pathlib.Path(name).read_bytes()
    except OSError:
        continue
    assert b'must-stay-hidden' not in data and b'human outside' not in data, name
try:
    pathlib.Path({str(outside)!r}).write_text('escape')
except OSError:
    pass
else:
    raise AssertionError('outside write succeeded')
try:
    s=socket.socket();s.settimeout(1)
    assert s.connect_ex(('127.0.0.1', {port})) != 0
except OSError:
    pass
print('FLOW_ISOLATION_OK')
'''
    journal = None
    try:
        from isycode.turn_journal import TurnJournal
        journal = TurnJournal.begin(root)
        runner = CommandRunOwner(root, authority, ActionApprovalStore())
        preview = runner.prepare(['bash', '-c', "python3 -c " + __import__('shlex').quote(code)])
        outcome = asyncio.run(runner.run(preview, None))
        assert outcome.decision == 'ALLOW', outcome.reason
        result = json.loads(outcome.text)
        assert 'FLOW_ISOLATION_OK' in result['output'], result
        assert outside.read_text() == 'human outside\n'
    finally:
        listener.close()
        if journal is not None:
            journal.finish()
