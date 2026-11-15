"""Memory ceilings of the command sandbox, and staging that never copies masked paths."""
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import isycode.platform_posix_sandbox as posix_sandbox
from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner, sandbox_executable, sensitive_entries
from isycode.platform_posix_sandbox import (
    SANDBOX_MASK_BYTES, SANDBOX_TMP_BYTES, PosixSandbox, command_bootstrap, memory_limit_bytes,
    memory_scope, sandbox_command,
)
from isycode.staging import (
    StagingError, cleanup_staging, measure_changes, prepare_staging, promote_changes,
)
from isycode.workspace_authority import WorkspaceAuthority

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX sandbox backend")


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "conf").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("keep\n", encoding="utf-8")
    (root / ".env").write_text("TOKEN=supersecret\n", encoding="utf-8")
    (root / "conf" / "server.pem").write_text("private-key\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "pack").write_bytes(b"g" * 4096)
    return root


def _staged_text(staging) -> str:
    return "".join(path.read_text(encoding="utf-8", errors="replace")
                   for path in staging.root.rglob("*") if path.is_file())


def test_every_tmpfs_has_a_size(tmp_path):
    command = sandbox_command("/usr/bin/bwrap", tmp_path, "/usr/bin/echo", ("echo",), ".",
                              ((".git", True), (".env", False)))
    mounts = [index for index, item in enumerate(command) if item == "--tmpfs"]
    assert [command[index + 1] for index in mounts] == ["/tmp", "/workspace/.git"]
    assert all(command[index - 2] == "--size" for index in mounts)
    assert [int(command[index - 1]) for index in mounts] == [SANDBOX_TMP_BYTES, SANDBOX_MASK_BYTES]


def test_the_per_process_limit_is_only_the_fallback():
    assert "RLIMIT_DATA" not in command_bootstrap(5)
    assert "resource.setrlimit(resource.RLIMIT_DATA, (4096, 4096))" in command_bootstrap(5, 4096)
    for bad in (0, -1, True, "1"):
        with pytest.raises(ValueError):
            command_bootstrap(5, bad)
    assert 1024**3 <= memory_limit_bytes() <= 8 * 1024**3


def test_the_memory_scope_is_checked_once_and_refused_without_a_user_manager(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs["env"]))
        return SimpleNamespace(returncode=answer)

    monkeypatch.setattr(posix_sandbox.subprocess, "run", fake_run)
    monkeypatch.setattr(posix_sandbox.os, "access", lambda path, mode: True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/test")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/test/bus")
    monkeypatch.setenv("SECRET_TOKEN", "never-forwarded")

    answer = 0
    monkeypatch.setattr(posix_sandbox, "_scope_ready", None)
    prefix = memory_scope(2 * 1024**3)
    assert prefix[:4] == ["/usr/bin/systemd-run", "--user", "--scope", "--quiet"]
    assert f"MemoryMax={2 * 1024**3}" in prefix and "MemorySwapMax=0" in prefix
    assert prefix[-2:] == ["/usr/bin/env", "-i"]
    assert memory_scope(1024**3)[-2:] == ["/usr/bin/env", "-i"] and len(calls) == 1
    assert calls[0][1] == {"XDG_RUNTIME_DIR": "/run/user/test",
                           "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/test/bus"}

    answer = 1
    monkeypatch.setattr(posix_sandbox, "_scope_ready", None)
    assert memory_scope(1024**3) == []

    monkeypatch.setattr(posix_sandbox, "_scope_ready", None)
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert memory_scope(1024**3) == [] and len(calls) == 2
    with pytest.raises(ValueError):
        memory_scope(0)


def test_a_reaped_process_is_never_signalled(monkeypatch):
    signalled = []
    monkeypatch.setattr(posix_sandbox.os, "killpg", lambda pid, sig: signalled.append(pid))
    backend = PosixSandbox()
    backend.terminate(SimpleNamespace(pid=4242, returncode=0))
    assert signalled == []
    backend.terminate(SimpleNamespace(pid=4242, returncode=None))
    assert signalled == [4242]


def test_masked_paths_are_not_copied_and_do_not_use_the_budget(tmp_path):
    root = _project(tmp_path)
    masks = sensitive_entries(root)
    assert masks == ((".env", False), (".git", True), ("conf/server.pem", False))
    with pytest.raises(StagingError):
        prepare_staging(root, max_stage_bytes=64)
    staging = prepare_staging(root, max_stage_bytes=64, masked=masks)
    try:
        staged = _staged_text(staging)
        assert "supersecret" not in staged and "private-key" not in staged
        assert (staging.root / ".env").read_bytes() == b""
        assert (staging.root / "conf" / "server.pem").read_bytes() == b""
        assert (staging.root / ".git").is_dir() and not list((staging.root / ".git").iterdir())
        assert {path: entry[0] for path, entry in staging.baseline.items()} == {
            ".env": "masked", ".git": "masked", "conf": "dir", "conf/server.pem": "masked",
            "src": "dir", "src/app.py": "file"}
        assert measure_changes(staging) == []
    finally:
        cleanup_staging(staging)


def test_a_moved_parent_never_promotes_a_placeholder(tmp_path):
    root = _project(tmp_path)
    (root / "conf" / "note.txt").write_text("note\n", encoding="utf-8")
    # A harmless name that is masked, like a hardlink to a secret in Flow.
    (root / "conf" / "linked.txt").write_text("same inode as a secret\n", encoding="utf-8")
    masks = (*sensitive_entries(root), ("conf/linked.txt", False))
    staging = prepare_staging(root, masked=masks)
    try:
        (staging.root / "conf").rename(staging.root / "moved")
        (staging.root / "conf").mkdir()
        (staging.root / "conf" / "linked.txt").write_text("overwrite\n", encoding="utf-8")
        changes = measure_changes(staging)
        applied, refused = promote_changes(staging, changes)
        assert sorted(applied) == ["conf/note.txt", "moved/note.txt"]
        assert {"conf/linked.txt", "conf/server.pem", "moved/linked.txt",
                "moved/server.pem"} <= set(refused)
        assert (root / "conf" / "linked.txt").read_text(encoding="utf-8") == "same inode as a secret\n"
        assert (root / "conf" / "server.pem").read_text(encoding="utf-8") == "private-key\n"
        assert not (root / "moved" / "linked.txt").exists()
        assert not (root / "moved" / "server.pem").exists()
        assert (root / "moved" / "note.txt").read_text(encoding="utf-8") == "note\n"
    finally:
        cleanup_staging(staging)


def test_a_secret_created_after_review_stops_the_copy(tmp_path):
    root = _project(tmp_path)
    masks = sensitive_entries(root)
    (root / "src" / ".env.local").write_text("LATE=secret\n", encoding="utf-8")
    before = set(Path(tempfile.gettempdir()).glob("isycode-stage-*"))
    with pytest.raises(StagingError, match="appeared after review"):
        prepare_staging(root, masked=masks)
    assert set(Path(tempfile.gettempdir()).glob("isycode-stage-*")) == before


def test_scoped_staging_matches_masks_by_workspace_path(tmp_path):
    root = _project(tmp_path)
    masks = tuple(("conf/" + path, folder) for path, folder in sensitive_entries(root / "conf"))
    staging = prepare_staging(root, scope="conf", masked=masks)
    try:
        assert (staging.root / "conf" / "server.pem").read_bytes() == b""
        assert not (staging.root / ".env").exists()
        assert measure_changes(staging) == []
    finally:
        cleanup_staging(staging)


def _real_sandbox_ready() -> bool:
    found = sandbox_executable()
    if not found:
        return False
    try:
        return subprocess.run([found, "--unshare-all", "--ro-bind", "/", "/", "/usr/bin/true"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _real_sandbox_ready(), reason="needs a working bubblewrap sandbox")
def test_real_sandbox_bounds_tmpfs_memory_and_hides_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _project(tmp_path)
    (root / ".isyroot").write_text("id\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("workspace.command.run", enabled=True, executables=[sandbox_executable()])
    approvals = ActionApprovalStore()
    owner = CommandRunOwner(root, authority, approvals)
    probe = (
        "import os, shutil, sys\n"
        "print('TMP', shutil.disk_usage('/tmp').total)\n"
        "print('GIT', shutil.disk_usage('/workspace/.git').total)\n"
        "print('ENVIRON', repr(open('/proc/1/environ', 'rb').read()))\n"
        "for name in ('.env', 'conf/server.pem'):\n"
        "    try:\n"
        "        print('READ', name, repr(open(name).read()))\n"
        "    except OSError as exc:\n"
        "        print('READ', name, 'denied')\n"
        "print('GITDIR', os.listdir('.git'))\n"
        "try:\n"
        "    with open('/tmp/fill', 'wb') as out:\n"
        "        block = b'x' * (8 * 1024 * 1024)\n"
        "        while True:\n"
        "            out.write(block)\n"
        "except OSError as exc:\n"
        "    print('FILL', os.path.getsize('/tmp/fill'), exc.errno)\n")
    preview = owner.prepare(["python3", "-c", probe], timeout_s=60)
    outcome = asyncio.run(owner.run_staged(preview, approvals.issue(preview.request)))
    assert outcome.decision == "ALLOW", outcome.reason
    output = json.loads(outcome.text)["output"]
    lines = dict(line.split(" ", 1) for line in output.splitlines() if " " in line)
    assert int(lines["TMP"]) == SANDBOX_TMP_BYTES, output
    assert int(lines["GIT"]) == SANDBOX_MASK_BYTES, output
    assert lines["ENVIRON"] == "b''", output
    assert "supersecret" not in output and "private-key" not in output
    assert lines["GITDIR"] == "[]", output
    # RLIMIT_FSIZE stops one file at 512 MiB; the tmpfs itself stops at 1 GiB.
    assert int(lines["FILL"].split()[0]) <= SANDBOX_TMP_BYTES, output
    assert (root / ".env").read_text(encoding="utf-8") == "TOKEN=supersecret\n"
