"""Read-only workspace access through IsyMotron's granted Linux host."""
from __future__ import annotations

import sys
import difflib
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isycode.authority import (
    grant_fingerprint, load_workspace_read_grants, validate_workspace_path,
)
from isycode.config import find_isymotron_root
from isycode.receipts import IsyMotronReceiptVerifier


class WorkspaceUnavailable(RuntimeError):
    """The workspace cannot be read under the configured IsyMotron grants."""


@dataclass(frozen=True)
class WorkspaceRead:
    data: dict[str, Any]
    receipt_id: str
    verification_status: str
    verification_reason: str


@dataclass(frozen=True)
class DirectoryListing:
    read: WorkspaceRead | None
    entries: list[dict[str, Any]]
    ignored_count: int
    access_detail: str = ""


@dataclass(frozen=True)
class SearchOutcome:
    hits: list[dict[str, Any]]
    directories_scanned: int
    directories_unreadable: int
    truncated: bool


def virtual_grant_children(directory: Path, grant_roots: tuple[Any, ...] | list[Any]) -> list[dict[str, Any]]:
    """Build synthetic locked nodes from scoped grant metadata only."""
    children: dict[str, dict[str, Any]] = {}
    for grant_root in grant_roots:
        base = Path(grant_root.path).resolve(strict=True)
        if directory not in base.parents:
            continue
        relative = base.relative_to(directory)
        if not relative.parts:
            continue
        name = relative.parts[0]
        child = directory / name
        authorized_here = child.resolve(strict=True) == base
        children[name] = {"name": name, "kind": "directory",
                          "path": str(child), "locked": not authorized_here,
                          "bytes": 0}
    return list(children.values())


class IsyMotronWorkspace:
    """Read files only through filesystem.read and an existing local grant."""

    SUBJECT = "isycode-tui-files"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceUnavailable("The launch directory is not a directory.")
        if not sys.platform.startswith("linux"):
            raise WorkspaceUnavailable("The IsyMotron Linux filesystem host is unavailable on this platform.")

        isymotron_root = find_isymotron_root()
        for entry in (isymotron_root, isymotron_root / "core", isymotron_root / "hosts"):
            if str(entry) not in sys.path:
                sys.path.insert(0, str(entry))

        try:
            from isymotron.resources import fs_roots, to_uri
            from hosts.linux.host import LinuxHost
            from relay.loopback import LoopbackRelay
        except Exception as exc:
            raise WorkspaceUnavailable(
                f"Could not load the IsyMotron filesystem host ({type(exc).__name__})."
            ) from exc

        configured_grants, workspace_grants = load_workspace_read_grants(self.root)
        self._grant_snapshot = grant_fingerprint(configured_grants)
        self._host = LinuxHost(workspace_grants)
        self._relay = LoopbackRelay()
        self._relay.attach(self._host)
        self._host_id = self._host.identify().host_id
        self._receipt_verifier = IsyMotronReceiptVerifier()
        read_roots = fs_roots(self._host.grants.scopes.get("filesystem.read", {}))
        self._grant_roots = read_roots
        # workspace_root is the physical, canonical UI boundary. Every read is
        # translated back to a host URI only after checking actual grant roots.
        self._ignore_specs: dict[str, Any] = {}

    @property
    def workspace_root(self) -> Path:
        return self.root

    @property
    def authority_roots(self) -> tuple[Path, ...]:
        """Filesystem.read roots after intersection with workspace identity."""
        return tuple(Path(item.path).resolve(strict=True) for item in self._grant_roots)

    def _granted_root_for(self, path: Path):
        for grant_root in self._grant_roots:
            base = Path(grant_root.path).resolve(strict=True)
            if path == base or base in path.parents:
                return grant_root
        return None

    def _host_uri(self, path: Path) -> str | None:
        from isymotron.resources import to_uri
        return to_uri(str(path), self._grant_roots)

    def _physical_from_uri(self, uri: str) -> Path | None:
        from isymotron.resources import resolve_path
        value = resolve_path(uri, self._grant_roots)
        return Path(value) if isinstance(value, str) else None

    def _virtual_children(self, directory: Path) -> list[dict[str, Any]]:
        """Derive locked path segments only from narrower grant metadata."""
        return virtual_grant_children(directory, self._grant_roots)

    def read(self, logical_path: str) -> WorkspaceRead:
        """List a directory or read a text file through the host contract."""
        from isymotron.contracts import ExecutionRequest
        from windows.grants import Grants

        if grant_fingerprint(Grants.load()) != self._grant_snapshot:
            raise WorkspaceUnavailable(
                "IsyMotron grants changed after Files opened. Restart ISyCode after reviewing them.")

        path = validate_workspace_path(self.root, Path(logical_path))
        host_uri = self._host_uri(path)
        if host_uri is None:
            raise WorkspaceUnavailable(
                "Workspace root is known, but this path is outside the actual IsyMotron filesystem.read grants.")
        relative = path.relative_to(self.root).as_posix()
        if any(self.is_sensitive_name(part) for part in relative.split("/") if part):
            raise WorkspaceUnavailable("The workspace browser hides this sensitive path.")
        try:
            lease, decision = self._relay.request_lease(
                self._host_id, self.SUBJECT, "filesystem.read", 30.0, {})
            if lease is None:
                raise WorkspaceUnavailable(f"IsyMotron refused the read lease: {decision}")
            request = ExecutionRequest.make(
                host_id=self._host_id,
                subject=self.SUBJECT,
                capability="filesystem.read",
                params={"path": host_uri},
                lease_id=lease.lease_id,
                plan_id="isycode-workspace-browser",
            )
            receipt = self._relay.execute(request)
            if receipt.decision.decision.name != "ALLOW":
                raise WorkspaceUnavailable(
                    f"IsyMotron denied filesystem.read: {receipt.decision.reason}"
                )
        except WorkspaceUnavailable:
            raise
        except Exception as exc:
            raise WorkspaceUnavailable(
                f"IsyMotron filesystem.read failed ({type(exc).__name__})."
            ) from exc
        result = receipt.result or {}
        if not isinstance(result, dict):
            raise WorkspaceUnavailable("IsyMotron returned an invalid filesystem result.")
        if result.get("error"):
            raise WorkspaceUnavailable(
                f"IsyMotron filesystem.read failed in the host ({result['error']})."
            )

        try:
            verification = self._receipt_verifier.verify(
                receipt, self._host.claim_bundle(receipt.receipt_id))
        except Exception as exc:
            raise WorkspaceUnavailable(
                f"IsyMotron receipt verification failed ({type(exc).__name__}); data blocked.") from exc
        verification_status = getattr(verification.status, "value", verification.status)
        if verification_status != "PASS":
            raise WorkspaceUnavailable(
                f"IsyMotron receipt did not verify ({verification_status}): "
                f"{verification.reason}")
        if grant_fingerprint(Grants.load()) != self._grant_snapshot:
            raise WorkspaceUnavailable(
                "IsyMotron grants changed during the read; result blocked. Restart ISyCode "
                "after reviewing the updated grants.")
        return WorkspaceRead(
            data=result, receipt_id=receipt.receipt_id,
            verification_status=verification_status,
            verification_reason=verification.reason,
        )

    @staticmethod
    def is_sensitive_name(name: str) -> bool:
        lower = name.casefold()
        return (lower in {".git", ".isycode", ".ssh", ".aws", ".gnupg"}
                or lower == ".env" or lower.startswith(".env.")
                or lower in {"id_rsa", "id_ed25519", "credentials", "secrets.json"}
                or lower.endswith((".pem", ".key", ".p12", ".pfx")))

    def list_directory(self, logical_path: str, *, show_ignored: bool = False) -> DirectoryListing:
        """List a directory through the host and apply gitignore rules locally."""
        path = validate_workspace_path(self.root, Path(logical_path))
        if self._host_uri(path) is None:
            children = self._virtual_children(path)
            if children:
                return DirectoryListing(
                    None, children, 0,
                    "Workspace root is known. Locked paths come from grant metadata; "
                    "IsyMotron does not grant directory enumeration here.")
            return DirectoryListing(
                None, [], 0,
                "Workspace root is known, but this subtree cannot be enumerated without an actual filesystem.read grant.")
        read = self.read(logical_path)
        if read.data.get("kind") != "directory":
            raise WorkspaceUnavailable("Selected path is not a directory.")
        all_entries = read.data.get("entries") or []
        has_gitignore = any(isinstance(item, dict) and item.get("name") == ".gitignore"
                            and not item.get("symlink") for item in all_entries)
        if has_gitignore and not show_ignored:
            self._refresh_ignore_spec(logical_path)
        elif not has_gitignore:
            self._ignore_specs.pop(logical_path, None)
        entries, ignored_count = [], 0
        for item in all_entries:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if (not isinstance(name, str) or not name or item.get("symlink")
                    or self.is_sensitive_name(name)):
                continue
            if not show_ignored and self.is_ignored(logical_path, name,
                                                     item.get("kind") == "directory"):
                ignored_count += 1
                continue
            entry = dict(item)
            uri = item.get("uri")
            physical = self._physical_from_uri(uri) if isinstance(uri, str) else None
            if physical is None:
                continue
            # A hostile host result cannot make the browser cross the marker.
            try:
                entry["path"] = str(validate_workspace_path(self.root, physical))
            except WorkspaceUnavailable:
                continue
            entries.append(entry)
        return DirectoryListing(read, entries, ignored_count)

    def _refresh_ignore_spec(self, directory_uri: str) -> None:
        from pathspec import PathSpec

        self._ignore_specs.pop(directory_uri, None)
        try:
            gitignore = self.read(directory_uri.rstrip("/") + "/.gitignore")
        except WorkspaceUnavailable as exc:
            raise WorkspaceUnavailable(
                f"Could not read the listed .gitignore; refusing an incomplete filter: {exc}"
            ) from exc
        if gitignore.data.get("truncated"):
            raise WorkspaceUnavailable("The .gitignore file exceeds the host read limit; refusing an incomplete filter.")
        source = gitignore.data.get("text")
        if not isinstance(source, str):
            raise WorkspaceUnavailable("This directory's .gitignore is not valid UTF-8.")
        try:
            self._ignore_specs[directory_uri] = PathSpec.from_lines(
                "gitwildmatch", source.splitlines())
        except Exception as exc:
            raise WorkspaceUnavailable("Could not parse this directory's .gitignore.") from exc

    def is_ignored(self, parent_uri: str, name: str, is_directory: bool) -> bool:
        candidate = posixpath.join(parent_uri, name)
        if is_directory:
            candidate += "/"
        ignored = False
        # Parent rules apply first. A child .gitignore can then override them.
        specs = sorted(self._ignore_specs.items(), key=lambda item: len(item[0]))
        for base_uri, spec in specs:
            if parent_uri != base_uri and not parent_uri.startswith(base_uri.rstrip("/") + "/"):
                continue
            relative = candidate.removeprefix(base_uri.rstrip("/") + "/")
            check = spec.check_file(relative)
            if check.index is not None:
                ignored = bool(check.include)
        return ignored

    def search(self, query: str, *, show_ignored: bool = False,
               max_directories: int = 300, max_entries: int = 6000,
               max_results: int = 250) -> SearchOutcome:
        """Bounded fuzzy filename/path search using only granted host listings."""
        query = query.strip().casefold()
        if not query:
            return SearchOutcome([], 0, 0, False)
        pending = [(str(self.root), "", 0)]
        hits: list[dict[str, Any]] = []
        directories_scanned = 0
        directories_unreadable = 0
        entries_seen = 0
        truncated = False
        while pending:
            directory_uri, relative_dir, depth = pending.pop()
            if depth > 24 or directories_scanned >= max_directories or entries_seen >= max_entries:
                truncated = True
                break
            try:
                listing = self.list_directory(directory_uri, show_ignored=show_ignored)
            except WorkspaceUnavailable:
                directories_unreadable += 1
                continue
            directories_scanned += 1
            for item in listing.entries:
                entries_seen += 1
                name = item["name"]
                relative = posixpath.join(relative_dir, name) if relative_dir else name
                kind = item.get("kind", "file")
                child_path = item.get("path")
                if not isinstance(child_path, str):
                    continue
                if kind == "directory":
                    pending.append((child_path, relative, depth + 1))
                score = max(
                    difflib.SequenceMatcher(None, query, name.casefold()).ratio(),
                    difflib.SequenceMatcher(None, query, relative.casefold()).ratio(),
                )
                if query in relative.casefold():
                    score = max(score, 1.0 - len(relative) / 10000)
                if score >= 0.34:
                    hits.append({
                        "name": name, "relative": relative, "path": child_path,
                        "kind": kind, "bytes": item.get("bytes", 0), "score": score,
                    })
                if entries_seen >= max_entries:
                    truncated = bool(pending)
                    break
            if directories_scanned >= max_directories and pending:
                truncated = True
                break
        hits.sort(key=lambda hit: (-hit["score"], hit["relative"].casefold()))
        if len(hits) > max_results:
            hits = hits[:max_results]
            truncated = True
        return SearchOutcome(hits, directories_scanned, directories_unreadable, truncated)
