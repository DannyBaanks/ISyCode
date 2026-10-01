"""Sandboxed workspace commands: grant + fresh approval + CommandProcessBoundary + receipt."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import COMMAND_MAX_OUTPUT_BYTES, ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner, sandbox_command
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the command sandbox is POSIX only")

# Stand-in for bubblewrap: it cannot mount, so it maps /workspace back to the
# host folder, applies --chdir/--setenv/--clearenv and logs the masks it was
# asked to apply. The real seccomp bootstrap still runs before the program.
FAKE_BWRAP = r'''#!{python}
import json, os, sys
args = sys.argv[1:]
split = args.index("--")
options, rest = args[:split], args[split + 1:]
two = {{"--ro-bind", "--bind", "--symlink", "--setenv"}}
one = {{"--chdir", "--tmpfs", "--proc", "--dev", "--dir"}}
workspace, chdir, env, masks, readonly = None, "/", {{}}, [], []
i = 0
while i < len(options):
    flag = options[i]
    if flag in two:
        a, b = options[i + 1], options[i + 2]
        if flag == "--bind" and b == "/workspace":
            workspace = a
        elif flag == "--setenv":
            env[a] = b
        elif flag == "--ro-bind" and a == "/dev/null":
            masks.append(b)
        elif flag == "--ro-bind" and b.startswith("/workspace/"):
            readonly.append(b)
        i += 3
    elif flag in one:
        if flag == "--chdir":
            chdir = options[i + 1]
        elif flag == "--tmpfs" and options[i + 1].startswith("/workspace/"):
            masks.append(options[i + 1])
        i += 2
    else:
        i += 1
with open(os.environ["FAKE_BWRAP_LOG"], "w") as log:
    json.dump({{"masks": masks, "readonly": readonly, "options": options}}, log)
mapped = [workspace + item[len("/workspace"):] if item.startswith("/workspace") else item
          for item in rest]
os.chdir(workspace + chdir[len("/workspace"):])
os.execve(mapped[0], mapped, env)
'''


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "bwrap"
    fake.write_text(FAKE_BWRAP.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    log = tmp_path / "bwrap.json"
    monkeypatch.setenv("FAKE_BWRAP_LOG", str(log))
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    approvals = ActionApprovalStore()
    return CommandRunOwner(root, authority, approvals), authority, approvals, str(fake.resolve()), log


def _grant(authority, executable):
    authority.set_grant("workspace.command.run", enabled=True, executables=[executable])


def _run(owner, approvals, argv, **kwargs):
    preview = owner.prepare(argv, **kwargs)
    return preview, asyncio.run(owner.run(preview, approvals.issue(preview.request)))


def test_no_grant_denies_even_with_an_approval(sandbox):
    owner, _, approvals, _, log = sandbox
    _, outcome = _run(owner, approvals, ["echo", "hi"])
    assert outcome.decision == "DENY" and "grant" in outcome.reason
    assert not log.exists()


def test_every_run_needs_a_fresh_approval(sandbox):
    owner, authority, approvals, fake, log = sandbox
    _grant(authority, fake)
    preview = owner.prepare(["echo", "hi"])
    assert asyncio.run(owner.run(preview, None)).decision == "DENY"
    approval = approvals.issue(preview.request)
    assert asyncio.run(owner.run(preview, approval)).decision == "ALLOW"
    assert asyncio.run(owner.run(preview, approval)).decision == "DENY"


def test_an_approved_command_runs_in_the_workspace_and_is_journaled(sandbox):
    owner, authority, approvals, fake, _ = sandbox
    _grant(authority, fake)
    preview, outcome = _run(owner, approvals, ["python3", "-c",
                                               "import os; print(os.getcwd()); print(os.environ.get('HOME'))"],
                            cwd="src")
    result = json.loads(outcome.text)
    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    assert result["exit_code"] == 0 and not result["timed_out"]
    assert result["output"].splitlines() == [str(owner.root / "src"), "/tmp"]
    assert preview.program in {"/usr/local/bin/python3", "/usr/bin/python3", "/bin/python3"}
    assert ActionAuditJournal(owner.root).verify().receipts == 1


def test_fast_command_can_finish_before_parent_resumes(sandbox, monkeypatch):
    owner, authority, approvals, fake, _ = sandbox
    _grant(authority, fake)
    spawn = asyncio.create_subprocess_exec
    async def already_finished(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        await process.wait()
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', already_finished)
    _, outcome = _run(owner, approvals, ['echo', 'finished'])
    assert outcome.decision == 'ALLOW', outcome.reason
    result = json.loads(outcome.text)
    assert result['exit_code'] == 0 and result['output'] == 'finished\n'


def test_resource_limits_are_installed_before_the_command(sandbox):
    owner, authority, approvals, fake, _ = sandbox
    _grant(authority, fake)
    _, outcome = _run(owner, approvals, ['python3', '-c',
        'import json,resource;print(json.dumps([resource.getrlimit(which) for which in '
        '(resource.RLIMIT_CPU,resource.RLIMIT_NOFILE,resource.RLIMIT_FSIZE)]))'], timeout_s=7)
    assert outcome.decision == 'ALLOW', outcome.reason
    assert json.loads(json.loads(outcome.text)['output']) == [[17,17], [1024,1024], [512*1024**2]*2]


def test_exit_codes_timeouts_and_output_limits_are_reported(sandbox):
    owner, authority, approvals, fake, _ = sandbox
    _grant(authority, fake)
    _, failed = _run(owner, approvals, ["python3", "-c", "raise SystemExit(3)"])
    assert failed.decision == "ALLOW" and json.loads(failed.text)["exit_code"] == 3
    _, slow = _run(owner, approvals, ["python3", "-c", "import time; time.sleep(30)"], timeout_s=1)
    assert json.loads(slow.text)["timed_out"] is True
    _, loud = _run(owner, approvals, ["python3", "-c", "print('x' * 200000)"])
    result = json.loads(loud.text)
    assert result["output_truncated"] and len(result["output"]) == COMMAND_MAX_OUTPUT_BYTES


def test_sockets_are_denied_inside_the_sandbox(sandbox):
    owner, authority, approvals, fake, _ = sandbox
    _grant(authority, fake)
    _, outcome = _run(owner, approvals, ["python3", "-c", "import socket; socket.socket()"])
    result = json.loads(outcome.text)
    assert result["exit_code"] != 0 and "PermissionError" in result["output"]


def test_sensitive_paths_are_masked_and_the_marker_is_read_only(sandbox):
    owner, authority, approvals, fake, log = sandbox
    _grant(authority, fake)
    (owner.root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    (owner.root / ".git").mkdir()
    (owner.root / "src" / "server.pem").write_text("key\n", encoding="utf-8")
    (owner.root / "src" / "link.pem").symlink_to(owner.root / "src" / "app.py")
    preview, outcome = _run(owner, approvals, ["echo", "ok"])
    assert outcome.decision == "ALLOW"
    assert preview.request.parameters["masked_count"] == 3
    logged = json.loads(log.read_text())
    assert sorted(logged["masks"]) == ["/workspace/.env", "/workspace/.git", "/workspace/src/server.pem"]
    assert logged["readonly"] == ["/workspace/.isyroot"]
    command = sandbox_command(fake, owner.root, "/usr/bin/echo", ("echo",), ".", preview.masks)
    assert command.index("--bind") < command.index("--tmpfs", command.index("--bind"))
    assert "--clearenv" in command and "--die-with-parent" in command


def test_a_new_secret_after_review_denies_the_run(sandbox):
    owner, authority, approvals, fake, log = sandbox
    _grant(authority, fake)
    preview = owner.prepare(["echo", "ok"])
    (owner.root / "src" / ".env.local").write_text("TOKEN=x\n", encoding="utf-8")
    outcome = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert outcome.decision == "DENY" and "changed after review" in outcome.reason
    assert not log.exists()


@pytest.mark.parametrize("argv, kwargs", [
    ([], {}),
    (["echo", "a\x00b"], {}),
    (["no-such-program-isycode"], {}),
    (["/etc/passwd"], {}),
    (["../outside"], {}),
    (["echo"], {"cwd": ".."}),
    (["echo"], {"cwd": ".git"}),
    (["echo"], {"cwd": "missing"}),
    (["echo"], {"timeout_s": 0}),
    (["echo"], {"timeout_s": 10_000}),
])
def test_invalid_commands_are_refused_before_review(sandbox, argv, kwargs):
    owner = sandbox[0]
    with pytest.raises(ValueError):
        owner.prepare(argv, **kwargs)


def test_workspace_programs_run_by_relative_path_but_not_through_symlinks(sandbox):
    owner, authority, approvals, fake, _ = sandbox
    _grant(authority, fake)
    script = owner.root / "run.sh"
    script.write_text("#!/bin/sh\necho from-workspace\n", encoding="utf-8")
    script.chmod(0o755)
    preview, outcome = _run(owner, approvals, ["./run.sh"])
    assert preview.program == "/workspace/run.sh"
    assert json.loads(outcome.text)["output"].strip() == "from-workspace"
    (owner.root / "tools").symlink_to(owner.root)
    with pytest.raises(ValueError):
        owner.prepare(["tools/run.sh"])


@pytest.mark.parametrize("change", [
    {"program": "/etc/passwd"},
    {"network": "allowed"},
    {"cwd": "../x"},
    {"timeout_s": 0},
    {"executable": "/bin/sh"},
    {"extra": True},
])
def test_sentinel_rejects_forged_command_requests(sandbox, change):
    owner, authority, approvals, fake, _ = sandbox
    _grant(authority, fake)
    authority.set_grant("workspace.command.run", enabled=True, executables=[fake, "/bin/sh"])
    preview = owner.prepare(["echo", "ok"])
    params = {**dict(preview.request.parameters), **change}
    request = ActionRequest("workspace.command.run", owner.root, params.get("program"), params,
                            execution_owner="workspace_command")
    gate = ProductActionGate(owner.root, authority, owner_id="workspace_command")
    _, decision = gate.authorize(request, approvals=approvals, approval=approvals.issue(request))
    assert not decision.allowed


def test_classic_mode_never_implies_commands(sandbox):
    owner, authority, approvals, _, log = sandbox
    authority.set_mode("classic")
    _, outcome = _run(owner, approvals, ["echo", "hi"])
    assert outcome.decision == "DENY" and not log.exists()


def test_without_bubblewrap_nothing_can_be_prepared(sandbox, monkeypatch):
    owner = sandbox[0]
    monkeypatch.setattr("isycode.command_runner.shutil.which", lambda name: None)
    with pytest.raises(ValueError, match="bubblewrap"):
        owner.prepare(["echo", "hi"])
