"""Staging keeps the user tree intact until a measured promotion."""
import asyncio
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner, sandbox_executable
from isycode.staging import (
    StagingError, measure_changes, prepare_staging, promote_changes, remove_spill,
)
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner

pytestmark = pytest.mark.skipif(os.name != "posix", reason="staging uses POSIX copies and bubblewrap")


def _owner(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("keep\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("git\n", encoding="utf-8")
    (root / ".isyroot").write_text("id\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    return CommandRunOwner(root, authority, approvals), authority, approvals, root


def test_copy_breaks_hardlinks_and_promotion_skips_protected_paths(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    original = root / "a.txt"
    original.write_text("a\n", encoding="utf-8")
    os.link(original, root / "b.txt")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("git\n", encoding="utf-8")
    staging = prepare_staging(root)
    try:
        assert (staging.root / "a.txt").stat().st_ino != original.stat().st_ino
        (staging.root / "a.txt").write_text("changed\n", encoding="utf-8")
        (staging.root / ".git" / "config").write_text("pwned\n", encoding="utf-8")
        (staging.root / "fresh.txt").write_text("new\n", encoding="utf-8")
        assert original.read_text(encoding="utf-8") == "a\n"
        changes = measure_changes(staging)
        applied, refused = promote_changes(staging, changes)
    finally:
        from isycode.staging import cleanup_staging
        cleanup_staging(staging)
    assert original.read_text(encoding="utf-8") == "changed\n"
    assert (root / "fresh.txt").read_text(encoding="utf-8") == "new\n"
    assert (root / ".git" / "config").read_text(encoding="utf-8") == "git\n"
    assert ".git/config" in refused
    assert "a.txt" in applied and "fresh.txt" in applied


def test_promote_refuses_parent_paths_and_a_human_edit(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    staging = prepare_staging(root)
    try:
        (staging.root / "a.txt").write_text("staged\n", encoding="utf-8")
        applied, refused = promote_changes(staging, [
            {"path": "../outside.txt", "kind": "add"},
            {"path": "a.txt", "kind": "modify"},
        ])
        assert applied == [] or "a.txt" in applied
        assert "../outside.txt" in refused
        (root / "a.txt").write_text("human\n", encoding="utf-8")
        (staging.root / "a.txt").write_text("again\n", encoding="utf-8")
        # The baseline is the copy-time original, so the human edit blocks promotion.
        staging.baseline["a.txt"] = ("file", "stale", 0o644)
        _, refused_again = promote_changes(staging, [{"path": "a.txt", "kind": "modify"}])
    finally:
        from isycode.staging import cleanup_staging
        cleanup_staging(staging)
    assert "../outside.txt" not in [path.name for path in tmp_path.iterdir()]
    assert refused_again == ["a.txt"]
    assert (root / "a.txt").read_text(encoding="utf-8") == "human\n"


def test_shell_and_python_mutations_stay_staged_until_promote(tmp_path, monkeypatch):
    owner, authority, approvals, root = _owner(tmp_path, monkeypatch)
    fake = tmp_path / "bin"
    fake.mkdir()
    # Reuse the command-runner fake by putting a tiny echo stand-in is not enough:
    # this test drives the real owner through the suite's fake bwrap pattern.
    from tests.test_command_runner import FAKE_BWRAP
    import sys
    program = fake / "bwrap"
    program.write_text(FAKE_BWRAP.format(python=Path(sys.executable).resolve()), encoding="utf-8")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_BWRAP_LOG", str(tmp_path / "bwrap.json"))
    authority.set_grant("workspace.command.run", enabled=True, executables=[str(program.resolve())])
    (root / "src" / "gone.txt").write_text("gone\n", encoding="utf-8")
    script = root / "burst.sh"
    # Dash builtins only. An external mkdir forks, and RLIMIT_NPROC counts every
    # thread of this uid, so the fake (which is not a user namespace) cannot fork
    # on a desktop session. The real Bubblewrap test below uses mkdir and rm.
    script.write_text(
        "#!/bin/sh\ni=0\nwhile [ \"$i\" -lt 200 ]; do echo x > \"src/s$i.txt\"; "
        "i=$((i+1)); done\necho changed > src/app.py\n",
        encoding="utf-8")
    script.chmod(0o755)
    preview = owner.prepare(["./burst.sh"])
    staged = asyncio.run(owner.run_staged(preview, approvals.issue(preview.request)))
    body = json.loads(staged.text)
    assert staged.decision == "ALLOW", staged.reason
    assert body["exit_code"] == 0, body["output"]
    assert body["staging"]["pending_count"] >= 200
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "keep\n"
    assert list((root / "src").glob("s*.txt")) == []
    assert (root / "src" / "gone.txt").read_text(encoding="utf-8") == "gone\n"
    assert (root / ".git" / "config").read_text(encoding="utf-8") == "git\n"
    promoted = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert promoted.decision == "ALLOW", promoted.reason
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "changed\n"
    assert len(list((root / "src").glob("s*.txt"))) == 200

    python = (
        "import pathlib; root = pathlib.Path('.'); root.joinpath('py').mkdir(); "
        "[(root / 'py' / f'f{i}.txt').write_text('y\\n') for i in range(200)]; "
        "(root / 'src' / 'gone.txt').unlink(); "
        "(root / '.git' / 'config').write_text('pwned\\n')"
    )
    preview = owner.prepare(["python3", "-c", python])
    held = asyncio.run(owner.run_staged(preview, approvals.issue(preview.request)))
    assert held.decision == "ALLOW", held.reason
    assert not (root / "py").exists()
    assert (root / "src" / "gone.txt").is_file()
    assert (root / ".git" / "config").read_text(encoding="utf-8") == "git\n"
    landed = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert landed.decision == "ALLOW", landed.reason
    assert len(list((root / "py").glob("f*.txt"))) == 200
    assert not (root / "src" / "gone.txt").exists()
    assert (root / ".git" / "config").read_text(encoding="utf-8") == "git\n"
    assert ".git/config" in json.loads(landed.text)["staging"]["refused"]


def test_typed_spills_do_not_create_files_until_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_mode("classic")
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)
    spills = []
    for number in range(200):
        preview = owner.preview(f"bulk/{number}.txt", f"n{number}\n")
        spills.append(owner.stage_preview(preview))
    assert not (root / "bulk").exists()
    assert all(path.is_file() and root.resolve() not in path.resolve().parents for path in spills)
    for path in spills:
        remove_spill(path)
    preview = owner.preview("bulk/0.txt", "n0\n")
    outcome = owner.apply(preview, approvals.issue(preview.request))
    assert outcome.decision == "ALLOW"
    assert (root / "bulk" / "0.txt").read_text(encoding="utf-8") == "n0\n"


def test_a_workspace_over_the_budget_is_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr("isycode.staging.MAX_STAGE_BYTES", 4)
    root = tmp_path / "project"
    root.mkdir()
    (root / "big.txt").write_text("too big\n", encoding="utf-8")
    with pytest.raises(StagingError):
        prepare_staging(root)
    assert (root / "big.txt").read_text(encoding="utf-8") == "too big\n"


def test_low_disk_does_not_run_the_command(tmp_path, monkeypatch):
    owner, authority, approvals, root = _owner(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "isycode.staging.shutil.disk_usage",
        lambda _path: type("Usage", (), {"free": 0})(),
    )
    sandbox = sandbox_executable()
    if sandbox is None:
        pytest.skip("bubblewrap is not installed; host fallback is not used")
    authority.set_grant("workspace.command.run", enabled=True, executables=[sandbox])
    preview = owner.prepare(["echo", "nope"])
    outcome = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert outcome.decision == "ERROR"
    assert "not run" in outcome.reason
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "keep\n"


def test_a_dead_sandbox_does_not_fall_back_to_the_host(tmp_path, monkeypatch):
    owner, authority, approvals, root = _owner(tmp_path, monkeypatch)
    fake = tmp_path / "bin"
    fake.mkdir()
    program = fake / "bwrap"
    program.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ.get('PATH', '')}")
    found = sandbox_executable()
    if found is None:
        pytest.skip("sandbox ingredients are absent; nothing is prepared")
    authority.set_grant("workspace.command.run", enabled=True, executables=[found])
    preview = owner.prepare(["python3", "-c", "open('src/app.py','w').write('pwned\\n')"])
    outcome = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert outcome.decision == "ALLOW", outcome.reason
    assert json.loads(outcome.text)["exit_code"] == 1
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "keep\n"
    assert json.loads(outcome.text)["staging"]["promoted_count"] == 0


def test_promote_does_not_follow_a_swapped_parent_symlink(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "sub" / "old.txt").write_text("old\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("git\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("safe\n", encoding="utf-8")
    staging = prepare_staging(root)
    try:
        (staging.root / "sub" / "new.txt").write_text("new\n", encoding="utf-8")
        changes = measure_changes(staging)
        (root / "sub").rename(root / "sub-kept")
        (root / "sub").symlink_to(outside, target_is_directory=True)
        applied, refused = promote_changes(staging, changes)
        assert "sub/new.txt" in refused
        assert not (outside / "new.txt").exists()
        (root / "sub").unlink()
        (root / "sub").symlink_to(root / ".git", target_is_directory=True)
        _, refused_git = promote_changes(staging, changes)
    finally:
        from isycode.staging import cleanup_staging
        cleanup_staging(staging)
    assert (outside / "secret").read_text(encoding="utf-8") == "safe\n"
    assert not (outside / "new.txt").exists()
    assert (root / ".git" / "config").read_text(encoding="utf-8") == "git\n"
    assert "sub/new.txt" in refused_git
    assert applied == [] or "sub/new.txt" not in applied
    assert (root / "sub-kept" / "old.txt").read_text(encoding="utf-8") == "old\n"


def test_binary_space_and_unicode_keep_bytes_and_mode(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "data.bin").write_bytes(b"\x00\x01\xff")
    (root / "my file.txt").write_text("space\n", encoding="utf-8")
    (root / "café.txt").write_text("uno\n", encoding="utf-8")
    tool = root / "tool.sh"
    tool.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    tool.chmod(0o755)
    nested = root / "dir with space"
    nested.mkdir()
    (nested / "archivo.txt").write_text("old\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / ".git").write_text("gitdir: ../.git/modules/sub\n", encoding="utf-8")
    (root / "link").symlink_to(root / "data.bin")
    staging = prepare_staging(root)
    try:
        (staging.root / "data.bin").write_bytes(b"\x00\x01\xffNEW")
        (staging.root / "my file.txt").write_text("changed space\n", encoding="utf-8")
        (staging.root / "café.txt").write_text("dos\n", encoding="utf-8")
        (staging.root / "tool.sh").write_text("#!/bin/sh\necho changed\n", encoding="utf-8")
        (staging.root / "tool.sh").chmod(0o755)
        (staging.root / "dir with space" / "archivo.txt").write_text("nuevo\n", encoding="utf-8")
        added = staging.root / "nuevo archivo.txt"
        added.write_bytes(b"bin \xff\n")
        added.chmod(0o640)
        (staging.root / "sub" / ".git").write_text("pwned\n", encoding="utf-8")
        (staging.root / "link").unlink()
        (staging.root / "link").write_text("replaced\n", encoding="utf-8")
        changes = measure_changes(staging)
        paths = {item["path"] for item in changes}
        assert {"data.bin", "my file.txt", "café.txt", "tool.sh",
                "dir with space/archivo.txt", "nuevo archivo.txt",
                "sub/.git", "link"} <= paths
        applied, refused = promote_changes(staging, changes)
    finally:
        from isycode.staging import cleanup_staging
        cleanup_staging(staging)
    assert (root / "data.bin").read_bytes() == b"\x00\x01\xffNEW"
    assert (root / "my file.txt").read_text(encoding="utf-8") == "changed space\n"
    assert (root / "café.txt").read_text(encoding="utf-8") == "dos\n"
    assert "echo changed" in (root / "tool.sh").read_text(encoding="utf-8")
    assert stat.S_IMODE((root / "tool.sh").stat().st_mode) == 0o755
    assert (root / "dir with space" / "archivo.txt").read_text(encoding="utf-8") == "nuevo\n"
    assert (root / "nuevo archivo.txt").read_bytes() == b"bin \xff\n"
    assert stat.S_IMODE((root / "nuevo archivo.txt").stat().st_mode) == 0o640
    assert (root / "sub" / ".git").read_text(encoding="utf-8").startswith("gitdir:")
    assert (root / "link").is_symlink()
    assert "sub/.git" in refused and "link" in refused
    assert "data.bin" in applied and "nuevo archivo.txt" in applied


def _bubblewrap_namespace_works() -> bool:
    """True only when the same mount shape as the product can exec a program."""
    sandbox = sandbox_executable()
    if sandbox is None:
        return False
    args = [sandbox, "--die-with-parent", "--unshare-all", "--share-net",
            "--ro-bind", "/usr", "/usr"]
    for source, destination, alias in (("/bin", "/bin", "/usr/bin"),
                                       ("/lib", "/lib", "/usr/lib"),
                                       ("/lib64", "/lib64", "/usr/lib64")):
        if Path(source).is_symlink():
            args.extend(["--symlink", alias, destination])
        elif Path(source).exists():
            args.extend(["--ro-bind", source, destination])
    args.extend(["--proc", "/proc", "--dev", "/dev", "--", "/usr/bin/true"])
    try:
        completed = subprocess.run(args, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


@pytest.mark.skipif(
    not _bubblewrap_namespace_works(),
    reason="bubblewrap cannot create a namespace here; host fallback is not used")
def test_real_bubblewrap_keeps_attacks_inside_staging(tmp_path, monkeypatch):
    owner, authority, approvals, root = _owner(tmp_path, monkeypatch)
    sandbox = sandbox_executable()
    assert sandbox is not None
    authority.set_grant("workspace.command.run", enabled=True, executables=[sandbox])
    outside = tmp_path / "outside.txt"
    outside.write_text("safe\n", encoding="utf-8")
    neighbor = tmp_path / "neighbor.txt"
    neighbor.write_text("neighbor\n", encoding="utf-8")
    (root / "link").symlink_to(outside)
    (root / ".env").write_text("TOKEN=supersecret\n", encoding="utf-8")
    (root / "src" / "gone.txt").write_text("gone\n", encoding="utf-8")
    tree = root / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("a\n", encoding="utf-8")
    (tree / "b.txt").write_text("b\n", encoding="utf-8")
    vault = tmp_path / "state" / "isycode" / "credentials.sqlite3"
    vault.parent.mkdir(parents=True, exist_ok=True)
    vault.write_text("vault-secret\n", encoding="utf-8")
    journal = tmp_path / "state" / "journal.jsonl"
    journal.write_text("journal\n", encoding="utf-8")
    checkpoint = tmp_path / "state" / "checkpoint.json"
    checkpoint.write_text("checkpoint\n", encoding="utf-8")
    marker = tmp_path / "authority" / "marker.txt"
    marker.write_text("authority\n", encoding="utf-8")
    script = root / "attack.sh"
    script.write_text(
        """#!/bin/sh
mkdir -p bulk
i=0
while [ "$i" -lt 200 ]; do
  echo x > "bulk/s$i.txt"
  i=$((i+1))
done
echo changed > src/app.py
rm -rf tree
rm -f src/gone.txt
echo pwned > .git/config
echo pwned > .isyroot
echo pwned > .env
echo pwned > link
echo pwned > /workspace/../neighbor.txt
echo pwned > "$1"
echo pwned > "$2"
echo pwned > "$3"
echo pwned > "$4"
echo "ROOTS:$(ls /)"
echo "ENV:$(cat .env 2>/dev/null || true)"
mkdir -p /tmp/m
if mount -t tmpfs tmpfs /tmp/m >/tmp/mount-err 2>&1; then
  echo MOUNT:ok
else
  echo MOUNT:denied
fi
echo DONE
""",
        encoding="utf-8")
    script.chmod(0o755)
    preview = owner.prepare([
        "./attack.sh", str(outside), str(vault), str(journal), str(marker)])
    outcome = asyncio.run(owner.run_staged(preview, approvals.issue(preview.request)))
    assert outcome.decision == "ALLOW", outcome.reason
    body = json.loads(outcome.text)
    assert body["exit_code"] == 0, body["output"]
    assert "DONE" in body["output"]
    assert "MOUNT:denied" in body["output"]
    assert "supersecret" not in body["output"]
    assert "vault-secret" not in body["output"]
    roots = body["output"].split("ROOTS:", 1)[1].split("ENV:", 1)[0]
    assert "home" not in roots.split()
    assert "workspace" in roots.split()
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "keep\n"
    assert (root / "src" / "gone.txt").read_text(encoding="utf-8") == "gone\n"
    assert (root / "tree" / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert not (root / "bulk").exists()
    assert outside.read_text(encoding="utf-8") == "safe\n"
    assert neighbor.read_text(encoding="utf-8") == "neighbor\n"
    assert (root / ".git" / "config").read_text(encoding="utf-8") == "git\n"
    assert (root / ".isyroot").read_text(encoding="utf-8") == "id\n"
    assert (root / ".env").read_text(encoding="utf-8") == "TOKEN=supersecret\n"
    assert vault.read_text(encoding="utf-8") == "vault-secret\n"
    assert journal.read_text(encoding="utf-8") == "journal\n"
    assert checkpoint.read_text(encoding="utf-8") == "checkpoint\n"
    assert marker.read_text(encoding="utf-8") == "authority\n"
    assert body["staging"]["pending_count"] >= 200
    assert body["staging"]["promoted_count"] == 0

    promoted = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert promoted.decision == "ALLOW", promoted.reason
    promoted_body = json.loads(promoted.text)
    promoted_paths = set(promoted_body["staging"]["promoted"])
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "changed\n"
    assert not (root / "src" / "gone.txt").exists()
    assert not (root / "tree").exists()
    assert len(list((root / "bulk").glob("s*.txt"))) == 200
    assert "src/app.py" in promoted_paths
    assert ".git/config" not in promoted_paths
    assert ".env" not in promoted_paths
    assert ".isyroot" not in promoted_paths
    assert (root / ".git" / "config").read_text(encoding="utf-8") == "git\n"
    assert (root / ".isyroot").read_text(encoding="utf-8") == "id\n"
    assert (root / ".env").read_text(encoding="utf-8") == "TOKEN=supersecret\n"
    assert outside.read_text(encoding="utf-8") == "safe\n"
    assert neighbor.read_text(encoding="utf-8") == "neighbor\n"
    assert vault.read_text(encoding="utf-8") == "vault-secret\n"
    assert journal.read_text(encoding="utf-8") == "journal\n"
    assert checkpoint.read_text(encoding="utf-8") == "checkpoint\n"
    assert marker.read_text(encoding="utf-8") == "authority\n"
    assert (root / "link").is_symlink()
