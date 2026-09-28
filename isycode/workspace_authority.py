"""Explicit per-.isyroot grants for ISyCode product actions.

The logical workspace root is only a maximum boundary. An absent policy or
grant denies. This module decides whether a request has an explicit grant;
the pure IsySentinel must still evaluate Systembilities before an owner acts.
"""
from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from isycode.security import ACTION_BY_ID, ActionRequest, AuthorityDecision
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.workspace_setup import state_root


class WorkspaceAuthorityError(RuntimeError):
    """Workspace grant state is invalid or unsafe to access."""


class WorkspaceAuthority:
    VERSION = 1
    MAX_POLICY_BYTES = 256 * 1024

    def __init__(self, workspace_root: Path, *, state_directory: Path | None = None):
        try:
            self.root = workspace_root.expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceAuthorityError("Workspace root cannot be resolved safely.") from exc
        if not self.root.is_dir():
            raise WorkspaceAuthorityError("Workspace root must be a directory.")
        self.state_directory = Path(state_directory or state_root()) / "workspace-authority"
        self.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.state_directory.is_symlink() or not self.state_directory.is_dir():
            raise WorkspaceAuthorityError("Authority state directory must be a real directory.")
        self.state_directory = self.state_directory.resolve(strict=True)
        if os.name == "posix":
            self.state_directory.chmod(0o700)
        self.root_id = __import__("hashlib").sha256(str(self.root).encode()).hexdigest()[:32]
        self.policy_path = self.state_directory / f"grants-{self.root_id}.json"

    def policy(self) -> dict[str, Any]:
        try:
            info = self.policy_path.lstat()
        except FileNotFoundError:
            return {"version": self.VERSION, "workspace_root": str(self.root), "grants": {}}
        except OSError as exc:
            raise WorkspaceAuthorityError("Workspace grant policy cannot be inspected.") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_size > self.MAX_POLICY_BYTES:
            raise WorkspaceAuthorityError("Workspace grant policy is not a bounded regular file.")
        try:
            data = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorkspaceAuthorityError("Workspace grant policy is unreadable or malformed.") from exc
        if (not isinstance(data, dict) or data.get("version") != self.VERSION
                or data.get("workspace_root") != str(self.root)
                or not isinstance(data.get("grants"), dict)):
            raise WorkspaceAuthorityError("Workspace grant policy does not match this root.")
        for action, grant in data["grants"].items():
            if action not in ACTION_BY_ID or not isinstance(grant, dict):
                raise WorkspaceAuthorityError("Workspace grant policy contains an unknown action.")
            if not isinstance(grant.get("enabled"), bool):
                raise WorkspaceAuthorityError("Workspace grant is malformed.")
            for key in ("path_prefixes", "network_hosts", "executables", "targets"):
                values = grant.get(key, [])
                if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                    raise WorkspaceAuthorityError("Workspace grant scopes are malformed.")
        return data

    def set_grant(self, action_id: str, *, enabled: bool,
                  path_prefixes: list[str | Path] | None = None,
                  network_hosts: list[str] | None = None,
                  executables: list[str | Path] | None = None,
                  targets: list[str] | None = None) -> None:
        """Persist one explicit grant. The Settings owner must obtain consent first."""
        if action_id not in ACTION_BY_ID or not isinstance(enabled, bool):
            raise ValueError("Unknown action or invalid enabled value.")
        existing = self.policy()
        grants = dict(existing["grants"])
        current = dict(grants.get(action_id, {}))
        current["enabled"] = enabled
        if path_prefixes is not None:
            current["path_prefixes"] = sorted({self._canonical_path(path) for path in path_prefixes})
        if network_hosts is not None:
            current["network_hosts"] = sorted({self._normalize_host(host) for host in network_hosts})
        if executables is not None:
            resolved = set()
            for executable in executables:
                path = Path(executable).expanduser().resolve(strict=True)
                if not path.is_file() or not os.access(path, os.X_OK):
                    raise ValueError("Executable scope must name an existing executable file.")
                resolved.add(str(path))
            current["executables"] = sorted(resolved)
        if targets is not None:
            current["targets"] = sorted({str(item)[:4096] for item in targets if item})
        grants[action_id] = current
        existing["grants"] = grants
        self._atomic_write(existing)

    def evaluate(self, request: ActionRequest, *,
                 approvals: ActionApprovalStore | None = None,
                 approval: ActionApproval | None = None) -> AuthorityDecision:
        if not isinstance(request, ActionRequest):
            return AuthorityDecision(False, "", "invalid action request", "")
        digest = request.digest
        if request.workspace_root != self.root:
            return AuthorityDecision(False, "", "request belongs to another workspace", digest)
        spec = ACTION_BY_ID.get(request.action_id)
        if spec is None:
            return AuthorityDecision(False, "", "unknown action is denied", digest)
        try:
            policy = self.policy()
        except WorkspaceAuthorityError:
            return AuthorityDecision(False, "", "workspace grant policy unavailable or invalid", digest)
        grant = policy["grants"].get(request.action_id, {})
        if not grant.get("enabled", False):
            return AuthorityDecision(False, "", "no explicit workspace grant", digest)

        if request.action_id.startswith(("workspace.files.", "workspace.context.")):
            try:
                target = self._canonical_path(request.target)
                roots = [self._canonical_path(item) for item in grant.get("path_prefixes", [])]
            except (OSError, ValueError, WorkspaceAuthorityError):
                return AuthorityDecision(False, "", "filesystem target is outside the workspace or unsafe", digest)
            if not roots or not any(self._contains(Path(root), Path(target)) for root in roots):
                return AuthorityDecision(False, "", "filesystem target is outside granted paths", digest)

        elif spec.effect.startswith("network"):
            try:
                host = self._normalize_host(request.target)
            except ValueError:
                return AuthorityDecision(False, "", "network target is not a valid host", digest)
            if host not in grant.get("network_hosts", []):
                return AuthorityDecision(False, "", "network host is not explicitly granted", digest)

        elif spec.effect == "process":
            executable = request.parameters.get("executable", "")
            try:
                binary = str(Path(executable).expanduser().resolve(strict=True))
            except (OSError, TypeError, ValueError):
                return AuthorityDecision(False, "", "process executable is unavailable", digest)
            if binary not in grant.get("executables", []):
                return AuthorityDecision(False, "", "process executable is not explicitly granted", digest)

        elif spec.effect in {"external", "destructive", "credential", "sensitive"}:
            if not request.target or request.target not in grant.get("targets", []):
                return AuthorityDecision(False, "", "action target is not explicitly granted", digest)

        if spec.approval_required:
            if approvals is None or not approvals.consume(request, approval):
                return AuthorityDecision(False, "", "fresh request-bound approval is required", digest)

        return AuthorityDecision(True, "grant:" + request.action_id,
                                 "explicit workspace grant matched", digest)

    def _canonical_path(self, value: str | Path) -> str:
        raw = Path(value).expanduser()
        lexical = raw if raw.is_absolute() else self.root / raw
        lexical = Path(os.path.abspath(lexical))
        if not self._contains(self.root, lexical):
            raise WorkspaceAuthorityError("path is outside .isyroot")
        cursor = self.root
        for part in lexical.relative_to(self.root).parts:
            cursor = cursor / part
            try:
                mode = cursor.lstat().st_mode
            except FileNotFoundError:
                break
            if stat.S_ISLNK(mode):
                raise WorkspaceAuthorityError("symlink traversal is denied")
        try:
            resolved = lexical.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceAuthorityError("path cannot be resolved") from exc
        if not self._contains(self.root, resolved):
            raise WorkspaceAuthorityError("resolved path escapes .isyroot")
        return str(resolved)

    @staticmethod
    def _contains(root: Path, path: Path) -> bool:
        return path == root or root in path.parents

    @staticmethod
    def _normalize_host(value: str) -> str:
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError("host is invalid")
        parsed = urlsplit(value if "://" in value else f"https://{value}")
        if parsed.username or parsed.password or not parsed.hostname:
            raise ValueError("host is invalid")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("scope accepts host only")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("port is invalid") from exc
        return parsed.hostname.casefold().rstrip(".") + (f":{port}" if port else "")

    def _atomic_write(self, value: Mapping[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
        temporary = self.state_directory / (".grants-" + secrets.token_hex(8) + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.policy_path)
            if os.name == "posix":
                self.policy_path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


__all__ = ["WorkspaceAuthority", "WorkspaceAuthorityError"]
