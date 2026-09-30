"""Reviewed, approved, descriptor-safe writes of one workspace text file."""
import os
from pathlib import Path

import pytest

from isycode.action_runtime import ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner

pytestmark = pytest.mark.skipif(os.name == "nt", reason="descriptor-safe writes are POSIX-only")


@pytest.fixture
def writer(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)
    return owner, authority, approvals, root.resolve()


def grant(authority, root):
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])


def test_preview_shows_the_exact_diff_and_writes_nothing(writer):
    owner, _, _, root = writer
    preview = owner.preview("src/app.py", "print('hello')\n")
    assert "-print('hi')" in preview.diff and "+print('hello')" in preview.diff
    assert preview.diff.startswith("--- a/src/app.py\n+++ b/src/app.py")
    assert preview.created is False
    assert (root / "src" / "app.py").read_text() == "print('hi')\n"


def test_write_requires_grant_and_fresh_approval(writer):
    owner, authority, approvals, root = writer
    preview = owner.preview("src/app.py", "x = 1\n")
    assert owner.apply(preview, approvals.issue(preview.request)).decision == "DENY"
    grant(authority, root)
    assert owner.apply(preview, None).decision == "DENY"
    assert (root / "src" / "app.py").read_text() == "print('hi')\n"


def test_approved_write_is_applied_verified_and_journaled(writer):
    owner, authority, approvals, root = writer
    grant(authority, root)
    (root / "src" / "app.py").chmod(0o640)
    preview = owner.preview("src/app.py", "x = 1\n")
    approval = approvals.issue(preview.request)
    outcome = owner.apply(preview, approval)

    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    assert (root / "src" / "app.py").read_text() == "x = 1\n"
    assert oct((root / "src" / "app.py").stat().st_mode & 0o777) == oct(0o640)
    assert not [p for p in (root / "src").iterdir() if p.name.endswith(".tmp")]
    # The same approval cannot be replayed, and the file no longer matches the preview.
    assert owner.apply(preview, approval).decision == "DENY"


def test_new_file_in_existing_folder(writer):
    owner, authority, approvals, root = writer
    grant(authority, root)
    preview = owner.preview("src/new.py", "y = 2\n")
    assert preview.created and preview.diff.startswith("--- /dev/null")
    assert preview.request.parameters["before_sha256"] == "absent"
    assert owner.apply(preview, approvals.issue(preview.request)).decision == "ALLOW"
    assert (root / "src" / "new.py").read_text() == "y = 2\n"


def test_file_changed_after_review_is_never_overwritten(writer):
    owner, authority, approvals, root = writer
    grant(authority, root)
    preview = owner.preview("src/app.py", "x = 1\n")
    (root / "src" / "app.py").write_text("edited by the user\n")
    outcome = owner.apply(preview, approvals.issue(preview.request))
    assert outcome.decision == "DENY" and "changed" in outcome.reason
    assert (root / "src" / "app.py").read_text() == "edited by the user\n"


@pytest.mark.parametrize("path", [
    "../outside.txt", "/etc/passwd", ".env", "src/.env.local", ".git/config",
    "keys/server.pem", ".", "", ".isyroot", "src/.ISYROOT",
])
def test_unsafe_or_sensitive_paths_are_refused_at_preview(writer, path):
    owner, _, _, _ = writer
    with pytest.raises(ValueError):
        owner.preview(path, "data\n")


def test_symlinked_file_or_folder_is_refused(writer, tmp_path):
    owner, authority, approvals, root = writer
    grant(authority, root)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    (root / "link.txt").symlink_to(outside)
    (root / "linkdir").symlink_to(tmp_path)
    with pytest.raises(OSError):
        owner.preview("link.txt", "pwned\n")
    with pytest.raises(OSError):
        owner.preview("linkdir/outside.txt", "pwned\n")
    assert outside.read_text() == "secret\n"


def test_limits_and_text_only(writer):
    owner, _, _, root = writer
    with pytest.raises(ValueError, match="128 KiB"):
        owner.preview("src/big.txt", "a" * (128 * 1024 + 1))
    (root / "src" / "blob.bin").write_bytes(b"\xff\xfe\x00binary")
    with pytest.raises(ValueError, match="UTF-8"):
        owner.preview("src/blob.bin", "text\n")
    with pytest.raises(FileNotFoundError):
        owner.preview("missing/dir/file.txt", "x\n")
    with pytest.raises(ValueError, match="already has"):
        owner.preview("src/app.py", "print('hi')\n")


def test_sentinel_refuses_a_forged_write_to_the_workspace_marker(writer):
    owner, authority, approvals, root = writer
    grant(authority, root)
    forged = ActionRequest("workspace.files.write", root, str(root / ".isyroot"), {
        "path": ".isyroot", "before_sha256": "absent", "after_sha256": "a" * 64,
        "size": 1, "diff_sha256": "b" * 64}, execution_owner="workspace_write")
    gate = ProductActionGate(root, authority, owner_id="workspace_write")
    assert not gate.authorize(forged, approvals=approvals,
                              approval=approvals.issue(forged))[1].allowed


@pytest.mark.parametrize("change", [
    {"path": "src/other.py"},
    {"size": 10 ** 9},
    {"after_sha256": "not-a-digest"},
    {"extra": True},
])
def test_sentinel_rejects_any_request_other_than_the_reviewed_one(writer, change):
    owner, authority, approvals, root = writer
    grant(authority, root)
    preview = owner.preview("src/app.py", "x = 1\n")
    parameters = {**preview.request.parameters, **change}
    forged = ActionRequest("workspace.files.write", root, preview.request.target, parameters,
                           execution_owner="workspace_write")
    gate = ProductActionGate(root, authority, owner_id="workspace_write")
    assert not gate.authorize(forged, approvals=approvals,
                              approval=approvals.issue(forged))[1].allowed


def test_write_grant_outside_the_granted_prefix_is_denied(writer):
    owner, authority, approvals, root = writer
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root / "src"])
    (root / "docs").mkdir()
    preview = owner.preview("docs/readme.md", "# hi\n")
    assert owner.apply(preview, approvals.issue(preview.request)).decision == "DENY"
    assert not (root / "docs" / "readme.md").exists()
