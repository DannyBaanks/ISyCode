"""Path-verified file I/O used on Windows, exercised on Linux through /proc/self/fd."""
import json
import os
from pathlib import Path

import pytest

import isycode.action_runtime as action_runtime
import isycode.workspace_write as workspace_write
from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.approvals import ActionApprovalStore
from isycode.winfs import VerifiedFS
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner

pytestmark = pytest.mark.skipif(not os.path.exists("/proc/self/fd"),
                                reason="needs /proc/self/fd to stand in for GetFinalPathNameByHandleW")


@pytest.fixture
def tree(tmp_path: Path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("x = 1\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "src" / "leak.txt").symlink_to(outside / "secret.txt")
    return root.resolve(), outside


def test_reads_refuse_links_anywhere_in_the_path(tree):
    root, _ = tree
    fs = VerifiedFS(root)
    fd = fs.open_read(root / "src" / "app.py")
    os.close(fd)
    for path in (root / "link" / "secret.txt", root / "src" / "leak.txt"):
        with pytest.raises(OSError):
            fs.open_read(path)
    names = {entry.name for entry in fs.list_dir(root / "src")}
    assert names == {"app.py"}


def test_a_handle_that_resolves_outside_is_refused(tree):
    root, outside = tree
    fs = VerifiedFS(root, final_path=lambda fd: str(outside / "secret.txt"))
    with pytest.raises(OSError, match="outside the workspace"):
        fs.open_read(root / "src" / "app.py")


def test_folders_are_created_only_when_approved(tree):
    root, _ = tree
    fs = VerifiedFS(root)
    with pytest.raises(FileNotFoundError):
        fs.ensure_folders(root / "new" / "deep", ())
    fs.ensure_folders(root / "new" / "deep", ("new", "new/deep"))
    assert (root / "new" / "deep").is_dir()
    with pytest.raises(OSError):
        fs.ensure_folders(root / "link" / "x", ("link/x",))


def test_replace_checks_the_current_content_and_verifies_the_result(tree):
    root, _ = tree
    fs = VerifiedFS(root)
    target = root / "src" / "app.py"
    reader = lambda: fs.read_file(target, 1024)  # noqa: E731
    with pytest.raises(ValueError):
        fs.replace(target, b"y = 2\n", b"stale\n", reader)
    fs.replace(target, b"y = 2\n", b"x = 1\n", reader)
    assert target.read_bytes() == b"y = 2\n"
    assert not [p for p in target.parent.iterdir() if p.name.endswith(".tmp")]


@pytest.fixture
def verified_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(action_runtime, "use_verified_fs", lambda: True)
    monkeypatch.setattr(workspace_write, "use_verified_fs", lambda: True)


def test_read_owner_works_in_verified_mode(tree, verified_mode, tmp_path):
    root, _ = tree
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("classic")
    owner = LocalWorkspaceReadOwner(root, authority)
    read = owner.execute("workspace.files.read", {"path": "src/app.py"})
    assert read.decision == "ALLOW" and json.loads(read.text)["text"] == "x = 1\n"
    listed = json.loads(owner.execute("workspace.files.list", {"path": "src"}).text)
    assert [entry["name"] for entry in listed["entries"]] == ["app.py"]
    grep = json.loads(owner.execute("workspace.files.read", {"path": ".", "query": "x ="}).text)
    assert [match["path"] for match in grep["matches"]] == ["src/app.py"]
    search = json.loads(owner.execute("workspace.files.search", {"query": "secret"}).text)
    assert search["matches"] == []
    assert owner.execute("workspace.files.read", {"path": "src/leak.txt"}).decision != "ALLOW"


def test_write_owner_edits_creates_and_undoes_in_verified_mode(tree, verified_mode, tmp_path):
    root, _ = tree
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("classic")
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)

    edit = owner.preview_edit("src/app.py", "x = 1", "x = 3")
    assert owner.apply(edit, approvals.issue(edit.request)).decision == "ALLOW"
    assert (root / "src" / "app.py").read_text() == "x = 3\n"

    created = owner.preview("pkg/new/mod.py", "y = 1\n")
    assert owner.apply(created, approvals.issue(created.request)).decision == "ALLOW"
    assert (root / "pkg" / "new" / "mod.py").read_text() == "y = 1\n"

    undo = owner.preview_undo()
    assert owner.apply(undo, approvals.issue(undo.request)).decision == "ALLOW"
    assert not (root / "pkg" / "new" / "mod.py").exists()

    with pytest.raises((OSError, ValueError)):
        blocked = owner.preview("link/evil.py", "z = 1\n")
        owner.apply(blocked, approvals.issue(blocked.request))
    assert not (tree[1] / "evil.py").exists()
