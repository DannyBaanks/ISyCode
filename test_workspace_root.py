"""Workspace marker discovery stays separate from IsyMotron authority."""
from __future__ import annotations

from pathlib import Path

import pytest

from isycode import config
from isycode import authority
from isycode.workspace import WorkspaceUnavailable, virtual_grant_children


def _discover(path: Path):
    assert hasattr(config, "discover_workspace_identity"), (
        "ISyCode does not yet discover .isyroot workspace identity"
    )
    return config.discover_workspace_identity(path)


def test_marker_in_launch_directory_is_workspace_root(tmp_path: Path):
    (tmp_path / ".isyroot").touch()

    identity = _discover(tmp_path)

    assert identity.launch_dir == tmp_path.resolve()
    assert identity.workspace_root == tmp_path.resolve()
    assert identity.workspace_root_source == "isyroot"


@pytest.mark.parametrize("depth", [1, 3])
def test_marker_in_parent_is_found_without_escaping_nearest_root(tmp_path: Path, depth: int):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".isyroot").touch()
    launch = root
    for index in range(depth):
        launch = launch / f"child-{index}"
        launch.mkdir()

    identity = _discover(launch)

    assert identity.workspace_root == root.resolve()
    assert identity.launch_dir == launch.resolve()
    assert identity.workspace_root_source == "isyroot"


def test_nearest_marker_wins(tmp_path: Path):
    outer = tmp_path / "outer"
    inner = outer / "inner"
    launch = inner / "project"
    launch.mkdir(parents=True)
    (outer / ".isyroot").touch()
    (inner / ".isyroot").touch()

    identity = _discover(launch)

    assert identity.workspace_root == inner.resolve()


def test_missing_marker_falls_back_to_canonical_launch_directory(tmp_path: Path):
    launch = tmp_path / "project"
    launch.mkdir()

    identity = _discover(launch)

    assert identity.workspace_root == launch.resolve()
    assert identity.workspace_root_source == "fallback"


def test_discovery_terminates_at_filesystem_root():
    identity = _discover(Path("/"))

    assert identity.launch_dir == Path("/")
    assert identity.workspace_root == Path("/")
    assert identity.workspace_root_source in {"isyroot", "fallback"}


def test_symlinked_launch_path_uses_canonical_workspace(tmp_path: Path):
    root = tmp_path / "real-root"
    launch = root / "project"
    launch.mkdir(parents=True)
    (root / ".isyroot").touch()
    alias = tmp_path / "launch-link"
    try:
        alias.symlink_to(launch, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    identity = _discover(alias)

    assert identity.launch_dir == launch.resolve()
    assert identity.workspace_root == root.resolve()


def test_symlink_marker_is_not_a_workspace_boundary(tmp_path: Path):
    launch = tmp_path / "project"
    launch.mkdir()
    external_marker = tmp_path / "marker-target"
    external_marker.touch()
    try:
        (launch / ".isyroot").symlink_to(external_marker)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    identity = _discover(launch)

    assert identity.workspace_root == launch.resolve()
    assert identity.workspace_root_source == "fallback"


def test_nonempty_marker_is_not_a_workspace_boundary(tmp_path: Path):
    launch = tmp_path / "project"
    launch.mkdir()
    (launch / ".isyroot").write_text("not an empty marker")

    identity = _discover(launch)

    assert identity.workspace_root == launch.resolve()
    assert identity.workspace_root_source == "fallback"


def test_navigation_parent_never_crosses_workspace_boundary(tmp_path: Path):
    root = tmp_path / "repo"
    child = root / "ISyCode" / "isycode"
    child.mkdir(parents=True)
    assert hasattr(authority, "workspace_parent"), "workspace boundary helper is missing"

    assert authority.workspace_parent(root, root) == root.resolve()
    assert authority.workspace_parent(root, child) == (root / "ISyCode").resolve()


def test_files_tree_virtual_root_contains_only_grant_derived_nodes(tmp_path: Path):
    from types import SimpleNamespace

    root = tmp_path / "ISyCo"
    authorized = root / "ISyCode" / "src"
    authorized.mkdir(parents=True)
    unrelated = root / "private"
    unrelated.mkdir()
    grant = SimpleNamespace(path=str(authorized))

    nodes = virtual_grant_children(root.resolve(), [grant])

    assert nodes == [{
        "name": "ISyCode", "kind": "directory",
        "path": str(root / "ISyCode"), "locked": True, "bytes": 0,
    }]
    deeper = virtual_grant_children((root / "ISyCode").resolve(), [grant])
    assert deeper[0]["name"] == "src"
    assert deeper[0]["locked"] is False
    authorized_node = virtual_grant_children((root / "ISyCode" / "src").resolve(), [grant])
    assert authorized_node == []


def test_workspace_path_rejects_any_parent_above_isyroot(tmp_path: Path):
    root = tmp_path / "repo"
    child = root / "project"
    child.mkdir(parents=True)

    with pytest.raises(WorkspaceUnavailable):
        authority.validate_workspace_path(root, root.parent)


def test_symlink_path_outside_workspace_is_rejected(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("private")
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    assert hasattr(authority, "validate_workspace_path"), "workspace path guard is missing"

    with pytest.raises(WorkspaceUnavailable):
        authority.validate_workspace_path(root, link / "secret.txt")


def test_syroot_does_not_create_or_widen_filesystem_grants(tmp_path: Path):
    root = tmp_path / "workspace"
    child_grant = root / "ISyCode"
    child_grant.mkdir(parents=True)
    (root / ".isyroot").touch()
    assert hasattr(authority, "narrow_read_roots"), "grant intersection helper is missing"

    narrowed = authority.narrow_read_roots(root, [
        {"id": "project", "label": "ISyCode", "path": str(child_grant)},
    ])

    assert [Path(item["path"]) for item in narrowed] == [child_grant.resolve()]
    assert Path(root).resolve() not in [Path(item["path"]) for item in narrowed]
    assert authority.narrow_read_roots(root, []) == []


def test_single_directory_grant_keeps_existing_workspace_behavior(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    assert hasattr(authority, "narrow_read_roots"), "grant intersection helper is missing"

    narrowed = authority.narrow_read_roots(root, [
        {"id": "home", "label": "Home", "path": str(tmp_path)},
    ])

    assert len(narrowed) == 1
    assert Path(narrowed[0]["path"]) == root.resolve()


def test_workspace_identity_keeps_launch_and_root_as_distinct_values(tmp_path: Path):
    root = tmp_path / "repo"
    launch = root / "project"
    launch.mkdir(parents=True)
    (root / ".isyroot").touch()

    identity = _discover(launch)

    assert identity.workspace_root == root.resolve()
    assert identity.launch_dir == launch.resolve()
    assert identity.workspace_root != identity.launch_dir
