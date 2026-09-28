"""ISySentinel: per-workspace, deny-by-default action policy for ISyCode.

``.isyroot`` defines the maximum workspace boundary. It never grants an
action. Per-root policy and receipts live in ISyCode's private state tree,
outside the project checkout. External providers, Gateway keys, MCP scopes,
and a selected role are credentials/configuration, not permissions.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from isycode.actions import ACTION_BY_ID, ACTION_CATALOG, ActionSpec
from isycode.config import WorkspaceIdentity
from isycode.workspace_setup import state_root


class SentinelConfigError(RuntimeError):
    """Policy state is missing, malformed, or cannot be safely persisted."""


@dataclass(frozen=True)
class Check:
    systembility: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class Authorization:
    allowed: bool
    action: str
    checks: tuple[Check, ...]
    receipt_id: str

    @property
    def status(self) -> str:
        return "ALLOW" if self.allowed else "DENY"

    @property
    def reason(self) -> str:
        failed = [item.reason for item in self.checks if not item.passed]
        return "; ".join(failed) if failed else "all IsySentinel checks passed"


@dataclass(frozen=True)
class ApprovalToken:
    token: str
    request_digest: str
    expires_at: float


class LegacyIsySentinelPrototype:
    """Deprecated combined policy prototype; do not use as a product gate."""

    VERSION = 1
    MAX_POLICY_BYTES = 256_000
    MAX_AUDIT_BYTES = 32 * 1024 * 1024

    def __init__(self, identity: WorkspaceIdentity, *, state_directory: Path | None = None):
        self.identity = identity
        try:
            self.root = identity.workspace_root.expanduser().resolve(strict=True)
        except OSError as exc:
            raise SentinelConfigError("The workspace root cannot be resolved.") from exc
        self.state_directory = Path(state_directory or state_root()) / "isysentinel"
        self.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.state_directory.is_symlink() or not self.state_directory.is_dir():
            raise SentinelConfigError("Sentinel state directory must be a real directory.")
        self.state_directory = self.state_directory.resolve(strict=True)
        if os.name == "posix":
            self.state_directory.chmod(0o700)
        self.identity_digest = hashlib.sha256(
            (str(self.root) + "\0" + identity.workspace_root_source).encode("utf-8")
        ).hexdigest()[:32]
        self.policy_path = self.state_directory / f"policy-{self.identity_digest}.json"
        self.audit_path = self.state_directory / f"audit-{self.identity_digest}.jsonl"
        self._approvals: dict[str, ApprovalToken] = {}

    def policy(self) -> dict[str, Any]:
        try:
            metadata = self.policy_path.lstat()
        except FileNotFoundError:
            return {"version": self.VERSION, "workspace": str(self.root),
                    "permissions": {}, "network_hosts": [], "executables": []}
        except OSError as exc:
            raise SentinelConfigError("Sentinel policy cannot be inspected safely.") from exc
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > self.MAX_POLICY_BYTES:
            raise SentinelConfigError("Sentinel policy is not a bounded regular file.")
        try:
            data = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SentinelConfigError("Sentinel policy is unreadable or malformed.") from exc
        if (not isinstance(data, dict) or data.get("version") != self.VERSION
                or data.get("workspace") != str(self.root)
                or not isinstance(data.get("permissions"), dict)):
            raise SentinelConfigError("Sentinel policy does not match this workspace.")
        permissions = data["permissions"]
        if any(action not in ACTION_BY_ID or not isinstance(enabled, bool)
               for action, enabled in permissions.items()):
            raise SentinelConfigError("Sentinel policy contains an unknown action or value.")
        hosts = data.get("network_hosts", [])
        executables = data.get("executables", [])
        if (not isinstance(hosts, list) or not all(isinstance(x, str) for x in hosts)
                or not isinstance(executables, list)
                or not all(isinstance(x, str) for x in executables)):
            raise SentinelConfigError("Sentinel scope lists are malformed.")
        return data

    def set_permission(self, action: str, enabled: bool) -> None:
        if action not in ACTION_BY_ID or not isinstance(enabled, bool):
            raise ValueError("Unknown IsySentinel action or permission value.")
        current = self.policy()
        permissions = dict(current.get("permissions", {}))
        permissions[action] = enabled
        current["permissions"] = permissions
        self._atomic_write(self.policy_path, current)

    def set_scopes(self, *, network_hosts: list[str] | None = None,
                   executables: list[str] | None = None) -> None:
        current = self.policy()
        if network_hosts is not None:
            hosts = sorted({self._normalize_host(host) for host in network_hosts})
            current["network_hosts"] = hosts
        if executables is not None:
            canonical: set[str] = set()
            for executable in executables:
                path = Path(executable).expanduser().resolve(strict=True)
                if not path.is_file() or not os.access(path, os.X_OK):
                    raise ValueError("Executable scope must name an existing executable file.")
                canonical.add(str(path))
            current["executables"] = sorted(canonical)
        self._atomic_write(self.policy_path, current)

    def issue_approval(self, action: str, *, path: str | Path | None = None,
                       target: str = "", ttl_s: float = 60.0) -> ApprovalToken:
        """Create a short-lived, one-use approval after a human confirmation UI."""
        if action not in ACTION_BY_ID:
            raise ValueError("Unknown IsySentinel action.")
        canonical = self._canonical_target(path) if path is not None else ""
        request_digest = self._request_digest(action, canonical, target)
        approval = ApprovalToken(secrets.token_urlsafe(24), request_digest,
                                 time.time() + max(1.0, min(ttl_s, 120.0)))
        self._approvals[approval.token] = approval
        return approval

    def authorize(self, action: str, *, path: str | Path | None = None,
                  target: str = "", executable: str | None = None,
                  approval: ApprovalToken | None = None,
                  details: Mapping[str, Any] | None = None) -> Authorization:
        """Evaluate all checks; an unavailable policy or check fails closed."""
        receipt_id = "sent_" + secrets.token_hex(8)
        spec = ACTION_BY_ID.get(action)
        checks: list[Check] = []
        checks.append(Check("KnownAction", spec is not None,
                            "unknown action" if spec is None else "action is registered"))
        try:
            policy = self.policy()
            checks.append(Check("PolicyIntegrity", True, "workspace policy loaded"))
        except SentinelConfigError as exc:
            checks.append(Check("PolicyIntegrity", False, str(exc)))
            policy = {"permissions": {}, "network_hosts": [], "executables": []}
        enabled = bool(policy.get("permissions", {}).get(action, False)) if spec else False
        checks.append(Check("ExplicitGrant", enabled,
                            "action is explicitly enabled" if enabled
                            else "action has no explicit workspace grant"))

        canonical = ""
        if path is not None:
            try:
                canonical = self._canonical_target(path)
                checks.append(Check("WorkspaceBoundary", True,
                                    "target is contained under .isyroot workspace root"))
            except (ValueError, OSError) as exc:
                checks.append(Check("WorkspaceBoundary", False, str(exc)))
        else:
            checks.append(Check("WorkspaceBoundary", True, "action has no filesystem target"))

        if target:
            try:
                hostname = self._normalize_host(target)
                host_allowed = hostname in set(policy.get("network_hosts", []))
                checks.append(Check("NetworkScope", host_allowed,
                                    "network target explicitly allowed" if host_allowed
                                    else "network target is not allowlisted"))
            except ValueError as exc:
                checks.append(Check("NetworkScope", False, str(exc)))
        else:
            checks.append(Check("NetworkScope", True, "action has no network target"))

        if executable is not None:
            try:
                binary = str(Path(executable).expanduser().resolve(strict=True))
                allowed = binary in set(policy.get("executables", []))
                checks.append(Check("ExecutionOwner", allowed,
                                    "executable is allowlisted" if allowed
                                    else "executable is not allowlisted"))
            except OSError:
                checks.append(Check("ExecutionOwner", False, "executable cannot be resolved"))
        else:
            checks.append(Check("ExecutionOwner", True, "no external executable requested"))

        needs_approval = bool(spec and spec.approval_required)
        expected = self._request_digest(action, canonical, target)
        valid_approval = bool(
            approval and approval.token in self._approvals
            and self._approvals[approval.token] == approval
            and approval.expires_at >= time.time()
            and approval.request_digest == expected
        )
        if valid_approval and approval:
            self._approvals.pop(approval.token, None)
        checks.append(Check("HumanApproval", not needs_approval or valid_approval,
                            "one-use approval verified" if valid_approval
                            else "action requires a fresh approval" if needs_approval
                            else "approval is not required"))

        allowed = all(item.passed for item in checks)
        decision = Authorization(allowed, action, tuple(checks), receipt_id)
        safe_details = self._redact(details or {})
        self._append_receipt(decision, canonical, target, safe_details)
        return decision

    def require(self, action: str, **kwargs: Any) -> Authorization:
        result = self.authorize(action, **kwargs)
        if not result.allowed:
            raise PermissionError(f"IsySentinel DENY {action}: {result.reason}")
        return result

    def _canonical_target(self, value: str | Path) -> str:
        root = self.root
        raw = Path(value).expanduser()
        lexical = raw if raw.is_absolute() else root / raw
        lexical = Path(os.path.abspath(lexical))
        try:
            relative = lexical.relative_to(root)
        except ValueError as exc:
            raise ValueError("target is outside the .isyroot sandbox") from exc
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            try:
                mode = cursor.lstat().st_mode
            except FileNotFoundError:
                # Non-existing leaf is valid for write; all existing parents
                # have already been inspected without following symlinks.
                break
            if stat.S_ISLNK(mode):
                raise ValueError("symlink traversal is denied by IsySentinel")
        try:
            resolved = lexical.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("target escapes the .isyroot sandbox") from exc
        return str(resolved)

    @staticmethod
    def _normalize_host(value: str) -> str:
        parsed = urlsplit(value if "://" in value else f"https://{value}")
        if parsed.username or parsed.password or not parsed.hostname:
            raise ValueError("network target must be a hostname without embedded credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("network scope accepts a host only, not a URL path")
        host = parsed.hostname.casefold().rstrip(".")
        port = parsed.port
        return f"{host}:{port}" if port else host

    @staticmethod
    def _request_digest(action: str, canonical_path: str, target: str) -> str:
        raw = json.dumps([action, canonical_path, target], separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def _redact(cls, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[depth-limited]"
        if isinstance(value, Mapping):
            cleaned = {}
            for key, item in value.items():
                label = str(key)
                if any(secret in label.casefold() for secret in
                       ("token", "secret", "password", "api_key", "authorization")):
                    cleaned[label] = "[redacted]"
                else:
                    cleaned[label] = cls._redact(item, depth + 1)
            return cleaned
        if isinstance(value, (list, tuple)):
            return [cls._redact(item, depth + 1) for item in value[:100]]
        if isinstance(value, str):
            return value[:2000]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return f"<{type(value).__name__}>"

    def _append_receipt(self, result: Authorization, path: str, target: str,
                        details: Mapping[str, Any]) -> None:
        entry = {
            "id": result.receipt_id,
            "time": time.time(),
            "workspace": self.identity_digest,
            "action": result.action,
            "decision": result.status,
            "path": str(Path(path).relative_to(self.root)) if path else "",
            "target": target,
            "checks": [item.__dict__ for item in result.checks],
            "details": details,
        }
        previous = "0" * 64
        try:
            if self.audit_path.exists():
                info = self.audit_path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size > self.MAX_AUDIT_BYTES:
                    raise SentinelConfigError("IsySentinel audit file is unsafe or full.")
                last = self.audit_path.read_text(encoding="utf-8").splitlines()[-1:]
                if last:
                    previous = str(json.loads(last[0]).get("digest", previous))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SentinelConfigError("IsySentinel audit chain cannot be read safely.") from exc
        entry["previous"] = previous
        serialized = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        entry["digest"] = hashlib.sha256((previous + serialized).encode("utf-8")).hexdigest()
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | nofollow
        try:
            fd = os.open(self.audit_path, flags, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            if os.name == "posix":
                self.audit_path.chmod(0o600)
        except OSError as exc:
            raise SentinelConfigError("IsySentinel could not write its audit receipt.") from exc

    def _atomic_write(self, path: Path, value: Mapping[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
        temporary = self.state_directory / (".policy-" + secrets.token_hex(8) + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            if os.name == "posix":
                path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


from isycode.security import (  # noqa: E402  (re-export after legacy definitions)
    ActionRequest, AuthorityDecision, DecisionCheck, IsySentinel,
    SentinelDecision, Systembility, SystembilityResult,
)

__all__ = [
    "ACTION_BY_ID", "ACTION_CATALOG", "ActionRequest", "ActionSpec",
    "AuthorityDecision", "Authorization", "DecisionCheck",
    "IsySentinel", "LegacyIsySentinelPrototype", "SentinelConfigError",
    "SentinelDecision", "Systembility", "SystembilityResult",
]
