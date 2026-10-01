"""Narrow IsyMotron grants to the workspace used by ISyCode."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from isycode.config import find_isymotron_root


def narrow_read_roots(workspace_root: Path, configured_roots: list[dict[str, str]]) -> list[dict[str, str]]:
    """Intersect actual grant roots with the logical workspace boundary."""
    workspace = workspace_root.expanduser().resolve(strict=True)
    narrowed: list[dict[str, str]] = []
    seen: set[Path] = set()
    for grant in configured_roots:
        try:
            granted = Path(grant["path"]).expanduser().resolve(strict=True)
        except (KeyError, OSError, RuntimeError):
            continue
        if granted == workspace or granted in workspace.parents:
            path = workspace
        elif workspace in granted.parents:
            path = granted
        else:
            continue
        if path in seen:
            continue
        seen.add(path)
        narrowed.append({
            "id": "workspace" if path == workspace else grant.get("id", "grant"),
            "label": workspace.name if path == workspace else grant.get("label", path.name),
            "path": str(path),
        })
    return narrowed


def workspace_parent(workspace_root: Path, candidate: Path) -> Path:
    """Return a canonical parent while clamping navigation at workspace root."""
    root = workspace_root.expanduser().resolve(strict=True)
    path = candidate.expanduser().resolve(strict=True)
    if path != root and root not in path.parents:
        return root
    parent = path.parent
    if path == root or parent == path or (parent != root and root not in parent.parents):
        return root
    return parent


def validate_workspace_path(workspace_root: Path, candidate: Path) -> Path:
    """Resolve an existing path under root, rejecting symlink traversal."""
    from isycode.workspace import WorkspaceUnavailable

    root = workspace_root.expanduser().resolve(strict=True)
    raw = candidate.expanduser()
    if not raw.is_absolute():
        raw = root / raw
    lexical = Path(os.path.abspath(raw))
    if lexical != root and root not in lexical.parents:
        raise WorkspaceUnavailable("The requested path is outside the workspace root.")
    try:
        cursor = root
        for part in lexical.relative_to(root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise WorkspaceUnavailable("The workspace browser does not follow symlinks.")
        resolved = lexical.resolve(strict=True)
    except FileNotFoundError as exc:
        raise WorkspaceUnavailable("The requested workspace path does not exist.") from exc
    except OSError as exc:
        raise WorkspaceUnavailable("The requested workspace path cannot be resolved safely.") from exc
    if resolved != root and root not in resolved.parents:
        raise WorkspaceUnavailable("The requested path resolves outside the workspace root.")
    return resolved


def load_workspace_read_grants(workspace_root: Path):
    """Load the current authority and return an in-memory read-only subset."""
    root = find_isymotron_root()
    for entry in (root, root / "core", root / "hosts"):
        value = str(entry)
        if value not in sys.path:
            sys.path.insert(0, value)

    from isymotron.resources import fs_roots
    from windows.grants import Grants

    configured = Grants.load()
    workspace = workspace_root.resolve(strict=True)
    configured_roots: list[dict[str, str]] = []
    if "filesystem.read" in configured.granted:
        for grant_root in fs_roots(configured.scopes.get("filesystem.read", {})):
            configured_roots.append({"id": grant_root.id, "label": grant_root.label,
                                     "path": grant_root.path})
    restricted = narrow_read_roots(workspace, configured_roots)

    read_granted = "filesystem.read" in configured.granted and bool(restricted)
    narrowed_grants = Grants(
        host_id=configured.host_id,
        display_name=configured.display_name,
        granted=["filesystem.read"] if read_granted else [],
        scopes={"filesystem.read": {"roots": restricted}} if read_granted else {},
        admin_granted=False,
        max_lease_ttl_s=min(configured.max_lease_ttl_s, 60.0),
        source=configured.source,
    )
    return configured, narrowed_grants


def grant_fingerprint(grants: Any) -> str:
    """Hash authority fields for change detection; never persist the grant data."""
    payload = {
        "host_id": grants.host_id,
        "display_name": grants.display_name,
        "granted": sorted(grants.granted),
        "scopes": grants.scopes,
        "admin_granted": grants.admin_granted,
        "max_lease_ttl_s": grants.max_lease_ttl_s,
        "source": grants.source,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
