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

AUTHORITY_GRANT_ALIASES = {
    "workspace.config.read": "workspace.files.read",
    "workspace.config.list": "workspace.files.list",
    "workspace.config.write": "workspace.files.write",
}


class WorkspaceAuthorityError(RuntimeError):
    """Workspace grant state is invalid or unsafe to access."""


class OneShotActionAuthority:
    """Overlay one human-approved request without persisting a workspace grant.

    ProductActionGate still runs ISySentinel, including owner binding and the
    filesystem boundary. The overlay accepts one immutable request digest once;
    every other request falls through to the normal WorkspaceAuthority policy.
    """

    def __init__(self, authority: "WorkspaceAuthority", approved_request: ActionRequest):
        self.authority = authority
        self._request_digest = approved_request.digest
        self._used = False

    def evaluate(self, request: ActionRequest, *, approvals=None, approval=None) -> AuthorityDecision:
        if not self._used and request.digest == self._request_digest:
            self._used = True
            return AuthorityDecision(
                True, "user-approved-once", "one exact request approved by the user",
                request.digest)
        return self.authority.evaluate(request, approvals=approvals, approval=approval)


MODES = frozenset({"security", "classic"})

# Classic mode is a per-workspace preset of implicit grants, not a bypass:
# IsySentinel, execution owners, per-action approvals (diff Apply, key save
# and removal) and the action journal are unchanged. Anything not listed here
# still needs an explicit grant, and explicitly denied actions stay denied.
CLASSIC_PATH_ACTIONS = frozenset({
    "workspace.files.list", "workspace.files.read", "workspace.files.search",
    "workspace.context.inject", "workspace.files.write", "workspace.files.restore",
    # Delete and move stay inside the workspace and still need a per-action approval.
    "workspace.files.delete", "workspace.files.move",
})
CLASSIC_PLAIN_ACTIONS = frozenset({"session.create", "session.resume", "git.status", "git.diff"})
CLASSIC_SERVICE_ACTIONS = frozenset({"credentials.add", "credentials.use", "credentials.revoke"})
CLASSIC_ACTIONS = (CLASSIC_PATH_ACTIONS | CLASSIC_PLAIN_ACTIONS | CLASSIC_SERVICE_ACTIONS
                   | {"provider.request"})


def _known_provider_hosts() -> list[str]:
    """Hosts of the provider presets and any configured endpoint override."""
    from isycode.providers import PRESETS, provider_base_url  # providers loads lazily

    urls = [str(preset.get("base_url", "")) for preset in PRESETS.values()]
    urls += [provider_base_url(name) for name in PRESETS]
    hosts = set()
    for url in urls:
        try:
            parsed = urlsplit(url.strip())
            if (parsed.scheme in {"http", "https"} and parsed.hostname
                    and not parsed.username and not parsed.password):
                hosts.add(parsed.hostname.casefold().rstrip(".")
                          + (f":{parsed.port}" if parsed.port else ""))
        except ValueError:
            continue
    for preset in PRESETS.values():
        hosts.update(preset.get("auth_hosts", []))
    return sorted(hosts)


def _known_services() -> list[str]:
    from isycode.providers import PRESETS

    return sorted(set(PRESETS) | {"isyco-gateway"})


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
        if not self._policy_file_safe(info) or info.st_size > self.MAX_POLICY_BYTES:
            raise WorkspaceAuthorityError("Workspace grant policy is not a bounded regular file.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.policy_path, flags)
            try:
                opened = os.fstat(descriptor)
                if (not self._policy_file_safe(opened)
                        or opened.st_dev != info.st_dev or opened.st_ino != info.st_ino
                        or opened.st_size > self.MAX_POLICY_BYTES):
                    raise WorkspaceAuthorityError("Workspace grant policy changed during inspection.")
                chunks: list[bytes] = []
                remaining = self.MAX_POLICY_BYTES + 1
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                after = os.fstat(descriptor)
                if (after.st_size != opened.st_size or after.st_mtime_ns != opened.st_mtime_ns
                        or after.st_ctime_ns != opened.st_ctime_ns):
                    raise WorkspaceAuthorityError("Workspace grant policy changed while reading.")
                payload = b"".join(chunks)
            finally:
                os.close(descriptor)
            if len(payload) > self.MAX_POLICY_BYTES:
                raise WorkspaceAuthorityError("Workspace grant policy exceeds its size limit.")
            data = json.loads(payload.decode("utf-8"))
        except WorkspaceAuthorityError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorkspaceAuthorityError("Workspace grant policy is unreadable or malformed.") from exc
        if (not isinstance(data, dict) or data.get("version") != self.VERSION
                or data.get("workspace_root") != str(self.root)
                or not isinstance(data.get("grants"), dict)
                or data.get("mode", "security") not in MODES):
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

    def mode(self) -> str | None:
        """Saved mode; None for a workspace that has never been configured."""
        if not self.policy_path.exists():
            return None
        return self.policy().get("mode", "security")

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError("Unknown workspace mode.")
        existing = self.policy()
        existing["mode"] = mode
        self._atomic_write(existing)

    def effective_policy(self) -> dict[str, Any]:
        """Explicit grants plus the Classic preset; what evaluate() decides on."""
        policy = self.policy()
        if policy.get("mode") != "classic":
            return policy
        grants = {action: dict(grant) for action, grant in policy["grants"].items()}

        def merge(action: str, key: str | None = None, values: list[str] | None = None) -> None:
            # An explicit denial overrides the implicit Classic preset.
            if grants.get(action, {}).get("enabled") is False:
                return
            current = grants.setdefault(action, {})
            current["enabled"] = True
            if key is not None:
                current[key] = sorted(set(current.get(key, [])) | set(values or []))

        for action in CLASSIC_PATH_ACTIONS:
            merge(action, "path_prefixes", [str(self.root)])
        for action in CLASSIC_PLAIN_ACTIONS:
            merge(action)
        services = _known_services()
        for action in CLASSIC_SERVICE_ACTIONS:
            merge(action, "targets", services)
        merge("provider.request", "network_hosts", _known_provider_hosts())
        return {**policy, "grants": grants}

    @staticmethod
    def _policy_file_safe(info: os.stat_result) -> bool:
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return False
        if os.name == "posix":
            return info.st_uid == os.getuid() and not (info.st_mode & 0o077)
        return True

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
            policy = self.effective_policy()
        except WorkspaceAuthorityError:
            return AuthorityDecision(False, "", "workspace grant policy unavailable or invalid", digest)
        if policy["grants"].get(request.action_id, {}).get("enabled") is False:
            return AuthorityDecision(False, "", "action explicitly revoked", digest)
        grant_action_id = AUTHORITY_GRANT_ALIASES.get(request.action_id, request.action_id)
        grant = policy["grants"].get(grant_action_id, {})
        if not grant.get("enabled", False):
            return AuthorityDecision(False, "", "no explicit workspace grant", digest)

        if (request.action_id.startswith(("workspace.files.", "workspace.context."))
                or request.action_id in AUTHORITY_GRANT_ALIASES):
            try:
                target = self._canonical_path(request.target)
                roots = [self._canonical_path(item) for item in grant.get("path_prefixes", [])]
            except (OSError, ValueError, WorkspaceAuthorityError):
                return AuthorityDecision(False, "", "filesystem target is outside the workspace or unsafe", digest)
            if not roots or not any(self._contains(Path(root), Path(target)) for root in roots):
                return AuthorityDecision(False, "", "filesystem target is outside granted paths", digest)
            if request.action_id == "workspace.files.move":
                # A move writes its destination too; it must be inside the same grant.
                try:
                    destination = self._canonical_path((request.parameters or {}).get("to", ""))
                except (OSError, ValueError, TypeError, WorkspaceAuthorityError):
                    return AuthorityDecision(False, "", "move destination is outside the workspace or unsafe", digest)
                if not any(self._contains(Path(root), Path(destination)) for root in roots):
                    return AuthorityDecision(False, "", "move destination is outside granted paths", digest)

        elif request.action_id == "provider.authenticate":
            from isycode.provider_auth import connector_scope_matches
            identity = request.parameters.get("connector", {})
            if not connector_scope_matches(grant, identity):
                return AuthorityDecision(False, "", "official connector executable, account and auth hosts need explicit grants", digest)

        elif spec.effect.startswith("network"):
            try:
                host = self._normalize_host(request.target)
            except ValueError:
                return AuthorityDecision(False, "", "network target is not a valid host", digest)
            if host not in grant.get("network_hosts", []):
                return AuthorityDecision(False, "", "network host is not explicitly granted", digest)
            if request.action_id == "provider.request" and request.parameters.get("provider") == "chatgpt":
                from isycode.provider_auth import AUTH_HOSTS, connector_scope_matches
                identity = request.parameters.get("connector", {})
                connector_grant = policy["grants"].get("provider.authenticate", {})
                if (not set(AUTH_HOSTS).issubset(grant.get("network_hosts", []))
                        or not connector_scope_matches(connector_grant, identity)):
                    return AuthorityDecision(False, "", "subscription connector and all authentication hosts need explicit grants", digest)


        elif spec.effect == "process":
            executable = (request.parameters or {}).get("executable", "")
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

        return AuthorityDecision(True, "grant:" + grant_action_id,
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


__all__ = ["CLASSIC_ACTIONS", "MODES", "WorkspaceAuthority", "WorkspaceAuthorityError"]
