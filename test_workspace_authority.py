from pathlib import Path

from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


def test_workspace_root_does_not_grant_filesystem_read_by_itself(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    request = ActionRequest("workspace.files.read", root, target="src/main.py")

    decision = authority.evaluate(request)

    assert not decision.allowed
    assert decision.request_digest == request.digest


def test_explicit_path_grant_allows_only_covered_workspace_paths(tmp_path):
    root = tmp_path / "project"
    source = root / "src"
    private = root / "private"
    source.mkdir(parents=True)
    private.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    authority.set_grant("workspace.files.read", enabled=True,
                        path_prefixes=[source])

    allowed = authority.evaluate(ActionRequest(
        "workspace.files.read", root, target="src/main.py"
    ))
    denied = authority.evaluate(ActionRequest(
        "workspace.files.read", root, target="private/secret.txt"
    ))

    assert allowed.allowed
    assert not denied.allowed


def test_path_grant_cannot_escape_isyroot_or_follow_symlink(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    authority.set_grant("workspace.files.read", enabled=True,
                        path_prefixes=[root])

    outside_decision = authority.evaluate(ActionRequest(
        "workspace.files.read", root, target=str(outside / "secret.txt")
    ))
    symlink_decision = authority.evaluate(ActionRequest(
        "workspace.files.read", root, target="link/secret.txt"
    ))

    assert not outside_decision.allowed
    assert not symlink_decision.allowed


def test_authority_rejects_a_request_for_another_workspace(tmp_path):
    root = tmp_path / "project"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    authority.set_grant("role.select", enabled=True)

    decision = authority.evaluate(ActionRequest("role.select", other))

    assert not decision.allowed


def test_corrupt_or_unknown_grants_fail_closed(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state")
    authority.policy_path.write_text('{"version": 999}', encoding="utf-8")

    decision = authority.evaluate(ActionRequest("role.select", root))

    assert not decision.allowed
