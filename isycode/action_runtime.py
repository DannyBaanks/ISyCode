"""Narrow local read-only action owner behind Authority and IsySentinel."""
from __future__ import annotations

import hashlib
import json
import os
import asyncio
import secrets
import shutil
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from isycode.actions import ACTION_BY_ID
from isycode.action_audit import ActionAuditError, ActionAuditJournal
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import (
    ActionRequest, AuthorityDecision, DecisionCheck, IsySentinel, SentinelDecision,
    SystembilityResult,
)
from isycode.workspace_authority import WorkspaceAuthority


READ_ACTIONS = frozenset({
    "workspace.files.list", "workspace.files.read", "workspace.files.search",
    "workspace.context.inject",
})
CHAT_WORKSPACE_TOOLS = [
    {"type": "function", "function": {
        "name": "workspace_list", "description": "List non-sensitive entries in an authorized workspace folder.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative folder path; defaults to the workspace root."},
        }, "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "workspace_read", "description": "Read one authorized UTF-8 text file up to 128 KiB.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
        }, "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "workspace_search", "description": "Search file and folder names, never file contents.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Text to find in names."},
            "path": {"type": "string", "description": "Workspace-relative folder path; defaults to the workspace root."},
        }, "required": ["query"], "additionalProperties": False},
    }},
]
TOOL_ACTIONS = {
    "workspace_list": "workspace.files.list",
    "workspace_read": "workspace.files.read",
    "workspace_search": "workspace.files.search",
}
MAX_FILE_BYTES = 128 * 1024
MAX_OUTPUT_CHARS = 24_000
MAX_SCAN_ENTRIES = 6_000


@dataclass(frozen=True)
class ActionReceipt:
    receipt_id: str
    action_id: str
    request_digest: str
    decision: str
    outcome: str
    result_digest: str

    def verify(self, request: ActionRequest, result: str) -> bool:
        return (self.decision == "ALLOW" and self.outcome == "SUCCESS"
                and self.request_digest == request.digest
                and self.result_digest == hashlib.sha256(result.encode("utf-8")).hexdigest())


@dataclass(frozen=True)
class ActionOutcome:
    text: str
    decision: str
    receipt: ActionReceipt | None
    reason: str


class WorkspaceReadSystembility:
    """Allow only bounded, non-sensitive reads inside the exact workspace."""

    name = "WorkspaceReadBoundary"

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in READ_ACTIONS:
            return SystembilityResult(self.name, True, "not applicable to this action")
        if request.workspace_root != self.root:
            return SystembilityResult(self.name, False, "request workspace does not match owner")
        target = request.target or str(self.root)
        raw = Path(target).expanduser()
        lexical = Path(os.path.abspath(raw if raw.is_absolute() else self.root / raw))
        if lexical != self.root and self.root not in lexical.parents:
            return SystembilityResult(self.name, False, "target escapes workspace root")
        current = self.root
        for part in lexical.relative_to(self.root).parts:
            current = current / part
            try:
                if stat.S_ISLNK(current.lstat().st_mode):
                    return SystembilityResult(self.name, False, "symlink traversal is denied")
            except FileNotFoundError:
                break
            except OSError:
                return SystembilityResult(self.name, False, "target metadata is unavailable")
        try:
            resolved = lexical.resolve(strict=False)
        except (OSError, RuntimeError):
            return SystembilityResult(self.name, False, "target cannot be canonicalized")
        if resolved != self.root and self.root not in resolved.parents:
            return SystembilityResult(self.name, False, "resolved target escapes workspace root")
        if any(self.is_sensitive_name(part) for part in resolved.relative_to(self.root).parts):
            return SystembilityResult(self.name, False, "sensitive paths are not available to chat tools")
        return SystembilityResult(self.name, True, "read-only target is inside the workspace")

    @staticmethod
    def is_sensitive_name(name: str) -> bool:
        lower = name.casefold()
        return (lower in {".git", ".isycode", ".ssh", ".aws", ".gnupg"}
                or lower == ".env" or lower.startswith(".env.")
                or lower in {"id_rsa", "id_ed25519", "credentials", "secrets.json"}
                or lower.endswith((".pem", ".key", ".p12", ".pfx")))


class ProviderNetworkSystembility:
    """Check that provider traffic uses an explicit, safe endpoint and host grant."""

    name = "ProviderNetworkBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id != "provider.request":
            return SystembilityResult(self.name, True, "not applicable to this action")
        url = request.parameters.get("url", "")
        if not isinstance(url, str) or len(url) > 2048:
            return SystembilityResult(self.name, False, "provider endpoint is invalid")
        parsed = urlsplit(url)
        if parsed.username or parsed.password or not parsed.hostname:
            return SystembilityResult(self.name, False, "provider endpoint must not contain credentials")
        loopback = parsed.hostname.casefold() in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            return SystembilityResult(self.name, False, "provider endpoint requires HTTPS outside loopback")
        try:
            host = parsed.hostname.casefold().rstrip(".") + (f":{parsed.port}" if parsed.port else "")
        except ValueError:
            return SystembilityResult(self.name, False, "provider endpoint port is invalid")
        if host != request.target.casefold().rstrip("."):
            return SystembilityResult(self.name, False, "provider endpoint host does not match the granted target")
        return SystembilityResult(self.name, True, "provider endpoint is secure and host-bound")


class RemoteReadSystembility:
    """Bound read-only catalog/health requests to one explicitly granted URL host."""

    name = "RemoteReadBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        spec = ACTION_BY_ID.get(request.action_id)
        if spec is None or not spec.effect.startswith("network") or request.action_id == "provider.request":
            return SystembilityResult(self.name, True, "not applicable to this action")
        if request.action_id not in {"gateway.files.read", "gateway.semantic.read",
                                     "mcp.discover", "catalog.external.read"}:
            if request.action_id == "mcp.invoke":
                return SystembilityResult(self.name, True, "MCP invocation is checked by its dedicated boundary")
            return SystembilityResult(self.name, False, "no remote read execution owner is registered")
        url = request.parameters.get("url", "")
        if not isinstance(url, str) or len(url) > 2048:
            return SystembilityResult(self.name, False, "remote endpoint is invalid")
        parsed = urlsplit(url)
        if parsed.username or parsed.password or not parsed.hostname or parsed.query or parsed.fragment:
            return SystembilityResult(self.name, False, "remote endpoint must not embed credentials or query data")
        loopback = parsed.hostname.casefold() in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            return SystembilityResult(self.name, False, "remote endpoint requires HTTPS outside loopback")
        try:
            host = parsed.hostname.casefold().rstrip(".") + (f":{parsed.port}" if parsed.port else "")
        except ValueError:
            return SystembilityResult(self.name, False, "remote endpoint port is invalid")
        if host != request.target.casefold().rstrip("."):
            return SystembilityResult(self.name, False, "remote endpoint does not match the granted host")
        return SystembilityResult(self.name, True, "remote read is secure and host-bound")


class SessionDeleteSystembility:
    """Bind destructive session removal to one validated local session id."""

    name = "SessionDeleteBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id != "session.delete":
            return SystembilityResult(self.name, True, "not applicable to this action")
        session_id = request.parameters.get("session_id")
        if (not isinstance(session_id, str) or len(session_id) != 32
                or any(char not in "0123456789abcdef" for char in session_id)
                or request.target != session_id):
            return SystembilityResult(self.name, False, "session delete target is invalid")
        return SystembilityResult(self.name, True, "delete is bound to one local session id")


class MCPInvocationSystembility:
    """Constrain the first invocation adapter to the configured Gateway MCP."""

    name = "MCPInvocationBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id != "mcp.invoke":
            return SystembilityResult(self.name, True, "not applicable to this action")
        server = request.parameters.get("server")
        tool = request.parameters.get("tool")
        schema_digest = request.parameters.get("schema_digest")
        url = request.parameters.get("url")
        arguments = request.parameters.get("arguments")
        if server != "isyco-gateway":
            return SystembilityResult(self.name, False, "only the configured ISyCo Gateway MCP is connected")
        if not isinstance(tool, str) or not tool or len(tool) > 160:
            return SystembilityResult(self.name, False, "MCP tool name is invalid")
        if (not isinstance(schema_digest, str) or len(schema_digest) != 64
                or any(char not in "0123456789abcdef" for char in schema_digest)):
            return SystembilityResult(self.name, False, "discovered tool schema fingerprint is invalid")
        if not isinstance(arguments, Mapping):
            return SystembilityResult(self.name, False, "MCP arguments must be an object")
        if not isinstance(url, str) or len(url) > 2048:
            return SystembilityResult(self.name, False, "Gateway endpoint is invalid")
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            return SystembilityResult(self.name, False, "Gateway endpoint must not contain credentials or query data")
        try:
            port = parsed.port
        except ValueError:
            return SystembilityResult(self.name, False, "Gateway endpoint port is invalid")
        loopback = parsed.hostname.casefold() in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            return SystembilityResult(self.name, False, "Gateway invocation requires HTTPS outside loopback")
        host = parsed.hostname.casefold().rstrip(".") + (f":{port}" if port else "")
        if request.target != f"isyco-gateway@{host}":
            return SystembilityResult(self.name, False, "Gateway invocation target does not match the approved host")
        return SystembilityResult(self.name, True, "one explicitly approved Gateway MCP call")


class GatewaySemanticSystembility:
    """Constrain native Gateway calls to typed, read-only semantic operations."""

    name = "GatewaySemanticBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id != "gateway.semantic.read":
            return SystembilityResult(self.name, True, "not applicable to this action")
        url = request.parameters.get("url")
        operation = request.parameters.get("operation")
        payload = request.parameters.get("payload")
        workspace_id = request.parameters.get("workspace_id")
        if not isinstance(operation, str) or not isinstance(payload, Mapping):
            return SystembilityResult(self.name, False, "semantic operation payload is invalid")
        expected_identity = os.environ.get("ISYCODE_GATEWAY_WORKSPACE_ID", "").strip()
        if (not expected_identity or not isinstance(workspace_id, str)
                or workspace_id != expected_identity):
            return SystembilityResult(self.name, False, "Gateway workspace identity is not explicitly bound")
        try:
            from isycode.semantic_gateway import validate_semantic_payload
            validate_semantic_payload(operation, payload)
        except (ImportError, TypeError, ValueError):
            return SystembilityResult(self.name, False, "semantic operation payload is outside its typed read-only contract")
        if not isinstance(url, str) or len(url) > 2048:
            return SystembilityResult(self.name, False, "Gateway endpoint is invalid")
        parsed = urlsplit(url)
        if (parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"} or not parsed.hostname):
            return SystembilityResult(self.name, False, "Gateway endpoint must contain only an origin")
        try:
            port = parsed.port
        except ValueError:
            return SystembilityResult(self.name, False, "Gateway endpoint port is invalid")
        loopback = parsed.hostname.casefold() in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            return SystembilityResult(self.name, False, "Gateway semantic calls require HTTPS outside loopback")
        host = parsed.hostname.casefold().rstrip(".") + (f":{port}" if port else "")
        if request.target != host:
            return SystembilityResult(self.name, False, "semantic request target does not match the Gateway host")
        return SystembilityResult(
            self.name, True, "one approved typed read-only operation bound to the configured workspace identity")


class LSPStartSystembility:
    """Allow only the Pyright workspace-symbol adapter inside bubblewrap."""

    name = "LSPProcessBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id != "lsp.start":
            return SystembilityResult(self.name, True, "not applicable to this action")
        try:
            from isycode.lsp import discover_servers
            servers = discover_servers()
            server = next((item for item in servers
                           if item.get("id") == request.parameters.get("server_id")), None)
            sandbox = str(Path(shutil.which("bwrap") or "").resolve(strict=True))
        except (OSError, RuntimeError, ValueError):
            return SystembilityResult(self.name, False, "sandboxed LSP adapter is unavailable")
        if server is None or server.get("state") != "sandbox_ready":
            return SystembilityResult(self.name, False, "selected LSP adapter is not sandbox-ready")
        if (request.target != server["id"]
                or request.parameters.get("operation") != "workspace/symbol"
                or request.parameters.get("executable") != sandbox
                or request.parameters.get("server_executable") != server["server_executable"]
                or request.parameters.get("node_executable") != server["node_executable"]
                or request.parameters.get("workspace_root") != str(request.workspace_root)):
            return SystembilityResult(self.name, False, "LSP request does not match the sandbox owner")
        query = request.parameters.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 256:
            return SystembilityResult(self.name, False, "LSP symbol query is invalid")
        return SystembilityResult(
            self.name, True,
            "known LSP server is restricted to a read-only workspace; seccomp denies socket syscalls")


class BrokerPreviewSystembility:
    """Bind broker previews to a project subtree and fixed hardening recipe."""

    name = "BrokerRecipeBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id != "broker.preview":
            return SystembilityResult(self.name, True, "not applicable to this action")
        try:
            project = Path(request.target).resolve(strict=True)
            digest = request.parameters.get("recipe_digest")
            source = Path(request.parameters.get("source_root", "")).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            return SystembilityResult(self.name, False, "broker root or recipe is unavailable")
        if (project != request.workspace_root and request.workspace_root not in project.parents):
            return SystembilityResult(self.name, False, "broker mount root escapes .isyroot")
        if not project.is_dir() or not source.is_dir():
            return SystembilityResult(self.name, False, "broker roots must be real directories")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            return SystembilityResult(self.name, False, "reviewed recipe digest is invalid")
        if (request.parameters.get("mount") != "read-only"
                or request.parameters.get("network") != "internal-only"
                or request.parameters.get("port_host") != "127.0.0.1"):
            return SystembilityResult(self.name, False, "broker preview weakens a required boundary")
        try:
            from isycode.broker import load_reviewed_recipe
            recipe = load_reviewed_recipe()
        except (OSError, RuntimeError, ValueError):
            return SystembilityResult(self.name, False, "reviewed semantic broker recipe is unavailable")
        if recipe.digest != digest or recipe.source_root != source:
            return SystembilityResult(self.name, False, "broker recipe changed after preview")
        return SystembilityResult(self.name, True,
                                  "fixed recipe, read-only project mount, internal network, loopback exposure")


class BrokerProvisionSystembility:
    """Bind build/start requests to the reviewed source, root, and hardening."""

    name = "BrokerProvisionBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if (request.action_id == "broker.start"
                and request.parameters.get("managed_existing") is True):
            return SystembilityResult(self.name, True,
                                      "existing-broker start is checked by the registry boundary")
        if request.action_id not in {"broker.build", "broker.start"}:
            return SystembilityResult(self.name, True, "not applicable to this action")
        try:
            project = Path(request.target).resolve(strict=True)
            docker = Path(request.parameters.get("executable", "")).resolve(strict=True)
            recipe_digest = request.parameters.get("recipe_digest")
            from isycode.broker import load_reviewed_recipe
            recipe = load_reviewed_recipe()
        except (OSError, RuntimeError, TypeError, ValueError):
            return SystembilityResult(self.name, False, "Docker or reviewed broker recipe is unavailable")
        if (project != request.workspace_root and request.workspace_root not in project.parents):
            return SystembilityResult(self.name, False, "broker project root escapes .isyroot")
        if not project.is_dir() or not docker.is_file() or not os.access(docker, os.X_OK):
            return SystembilityResult(self.name, False, "broker target or Docker executable is invalid")
        if recipe.digest != recipe_digest:
            return SystembilityResult(self.name, False, "broker recipe changed after human review")
        if request.action_id == "broker.build":
            if (request.parameters.get("operation") != "build"
                    or request.parameters.get("source_root") != str(recipe.source_root)
                    or request.parameters.get("build_network") != "docker-daemon-default"):
                return SystembilityResult(self.name, False, "build request differs from the reviewed recipe")
        else:
            if (request.parameters.get("operation") != "start"
                    or request.parameters.get("image") != f"isycode-semantic-broker:{recipe.digest[:16]}"
                    or request.parameters.get("network") != "internal"
                    or request.parameters.get("mount_read_only") is not True
                    or request.parameters.get("bind_host") != "127.0.0.1"
                    or request.parameters.get("credentials_mounted") is not False
                    or request.parameters.get("read_only") is not True
                    or request.parameters.get("cap_drop") != "ALL"
                    or request.parameters.get("no_new_privileges") is not True
                    or request.parameters.get("pids_limit") != 128
                    or request.parameters.get("memory_limit") != "2g"
                    or request.parameters.get("tmpfs_limit") != "128m"):
                return SystembilityResult(self.name, False, "start request weakens the reviewed sandbox")
        return SystembilityResult(self.name, True,
                                  "exact Docker executable, reviewed recipe, bounded workspace and sandbox")


class BrokerManagementSystembility:
    """Bind broker lifecycle operations to a private registered identity."""

    name = "BrokerRegistryBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        action_to_operation = {
            "broker.health": "health", "broker.logs": "logs",
            "broker.start": "start", "broker.stop": "stop", "broker.remove": "remove",
        }
        operation = action_to_operation.get(request.action_id)
        if request.action_id == "broker.start" and request.parameters.get("managed_existing") is not True:
            return SystembilityResult(self.name, True,
                                      "initial provision start is checked by the recipe boundary")
        if operation is None:
            return SystembilityResult(self.name, True, "not applicable to this action")
        try:
            project_path = Path(request.parameters.get("project_root", ""))
            docker = Path(request.parameters.get("executable", "")).resolve(strict=True)
            from isycode.broker import BrokerRegistry, _canonical_registered_project_path
            project = _canonical_registered_project_path(request.workspace_root, project_path)
            item = BrokerRegistry().get(request.workspace_root, project)
        except (OSError, RuntimeError, TypeError, ValueError):
            return SystembilityResult(self.name, False, "registered broker identity is unavailable")
        if item is None:
            return SystembilityResult(self.name, False, "broker is not registered for this workspace")
        expected = {
            "operation": operation, "project_root": str(project),
            "root_id": BrokerRegistry.root_id(project), "container": item["container"],
            "network": item["network"], "image": item["image"],
            "recipe_digest": item["recipe_digest"], "host_port": item["host_port"],
        }
        if operation == "start":
            expected["managed_existing"] = True
        if (project != request.workspace_root and request.workspace_root not in project.parents):
            return SystembilityResult(self.name, False, "broker root escapes .isyroot")
        if (request.target != item["container"]
                or not docker.is_file() or not os.access(docker, os.X_OK)
                or any(request.parameters.get(key) != value for key, value in expected.items())):
            return SystembilityResult(self.name, False, "broker request differs from its registered identity")
        if operation in {"stop", "remove"} and item.get("status") not in {"healthy", "stopped", "unverified"}:
            return SystembilityResult(self.name, False, "broker registry status is invalid")
        return SystembilityResult(self.name, True,
                                  "operation is bound to the registered broker and its exact workspace")


class ProductActionGate:
    """Run explicit Workspace Authority followed by the pure ISySentinel."""

    _OWNER_ACTIONS = {
        "workspace_read": READ_ACTIONS,
        "provider_network": frozenset({"provider.request"}),
        "remote_catalog": frozenset({"gateway.files.read", "mcp.discover", "catalog.external.read"}),
        "session_delete": frozenset({"session.delete"}),
        "gateway_mcp": frozenset({"mcp.invoke"}),
        "gateway_semantic": frozenset({"gateway.semantic.read"}),
        "lsp_symbols": frozenset({"workspace.files.read", "lsp.start"}),
        "broker_preview": frozenset({"workspace.files.read", "broker.preview"}),
        "broker_provision": frozenset({"workspace.files.read", "broker.build", "broker.start"}),
        "broker_management": frozenset({"broker.health", "broker.logs", "broker.start",
                                         "broker.stop", "broker.remove"}),
    }

    def __init__(self, root: Path, authority: WorkspaceAuthority, *, owner_id: str):
        canonical = root.resolve(strict=True)
        self.owner_id = owner_id if isinstance(owner_id, str) else ""
        allowed_actions = self._OWNER_ACTIONS.get(self.owner_id, frozenset())

        class ExecutionOwnerBindingSystembility:
            name = "ExecutionOwnerBinding"

            def evaluate(inner_self, request: ActionRequest,
                         authority_decision: AuthorityDecision) -> SystembilityResult:
                bound = request.execution_owner == self.owner_id and request.action_id in allowed_actions
                if not self.owner_id or not allowed_actions:
                    reason = "no execution owner is registered for this gate"
                elif request.execution_owner != self.owner_id:
                    reason = "request is bound to a different execution owner"
                elif request.action_id not in allowed_actions:
                    reason = "execution owner has no implementation for this action"
                else:
                    reason = "action is registered to this concrete execution owner"
                return SystembilityResult(inner_self.name, bound, reason)

        self.authority = authority
        try:
            self.audit: ActionAuditJournal | None = ActionAuditJournal(canonical)
        except ActionAuditError:
            self.audit = None
        self.sentinel = IsySentinel([
            ExecutionOwnerBindingSystembility(),
            WorkspaceReadSystembility(canonical), ProviderNetworkSystembility(),
            RemoteReadSystembility(), SessionDeleteSystembility(), MCPInvocationSystembility(),
            GatewaySemanticSystembility(), LSPStartSystembility(), BrokerPreviewSystembility(),
            BrokerProvisionSystembility(), BrokerManagementSystembility(),
        ])

    def authorize(self, request: ActionRequest, *, approvals: ActionApprovalStore | None = None,
                  approval: ActionApproval | None = None):
        authority = self.authority.evaluate(request, approvals=approvals, approval=approval)
        decision = self.sentinel.evaluate(request, authority)
        try:
            if self.audit is None:
                raise ActionAuditError("journal is unavailable")
            self.audit.record_decision(request, authority, decision)
        except ActionAuditError:
            decision = SentinelDecision(
                decision.action_id, decision.request_digest,
                decision.checks + (DecisionCheck(
                    "DurableActionJournal", False,
                    "authorization could not be durably recorded; action denied"),))
        return authority, decision

    def persist_receipt(self, request: ActionRequest, receipt: ActionReceipt) -> bool:
        try:
            if self.audit is None:
                return False
            self.audit.record_receipt(request, receipt)
        except ActionAuditError:
            return False
        return True


class SessionDeleteOwner:
    """Delete exactly one chat session after Authority, Sentinel and approval."""

    def __init__(self, root: Path, authority: WorkspaceAuthority, store: Any,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.store = store
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="session_delete")

    def delete(self, session_id: str, title: str,
               approval: ActionApproval | None) -> ActionOutcome:
        try:
            request = ActionRequest("session.delete", self.root, session_id,
                                    {"session_id": session_id, "title": title[:80]},
                                    execution_owner="session_delete")
        except (TypeError, ValueError):
            return ActionOutcome("Session deletion denied.", "DENY", None,
                                 "invalid session delete request")
        authority, decision = self.gate.authorize(
            request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome("Session deletion denied.", "DENY", None, reason)
        try:
            self.store.delete(session_id)
        except (OSError, ValueError):
            return ActionOutcome("Session deletion failed.", "ERROR", None,
                                 "session store rejected the delete")
        result = "deleted"
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "session.delete", request.digest, "ALLOW", "SUCCESS",
            hashlib.sha256(result.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result):
            return ActionOutcome("Session receipt failed verification.", "NOT_VERIFIABLE", None,
                                 "local request/result digest did not match")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Session receipt could not be persisted.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(result, "ALLOW", receipt, "approved one-session deletion")


class GatewayMCPInvocationOwner:
    """Run one Gateway MCP call only after local grant, Sentinel, and approval."""

    SERVER_ID = "isyco-gateway"

    @classmethod
    def target_for(cls, url: str) -> str:
        parsed = urlsplit(url)
        if not parsed.hostname:
            raise ValueError("Gateway MCP endpoint has no host")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Gateway MCP endpoint has an invalid port") from exc
        host = parsed.hostname.casefold().rstrip(".") + (f":{port}" if port else "")
        return f"{cls.SERVER_ID}@{host}"

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="gateway_mcp")

    async def invoke(self, tool_name: str, arguments: dict[str, Any], url: str,
                     schema_digest: str, discovered_tools: list[dict[str, Any]],
                     approval: ActionApproval | None) -> ActionOutcome:
        from isycode.gateway_mcp import tool_schema_digest

        catalog_tool = next((tool for tool in discovered_tools
                             if isinstance(tool, dict) and tool.get("name") == tool_name), None)
        if catalog_tool is None or tool_schema_digest(catalog_tool) != schema_digest:
            return ActionOutcome("MCP invocation denied.", "DENY", None,
                                 "tool is absent from the current discovered catalog")
        try:
            request = ActionRequest(
                "mcp.invoke", self.root, self.target_for(url),
                {"server": self.SERVER_ID, "tool": tool_name,
                 "arguments": arguments, "url": url, "schema_digest": schema_digest},
                execution_owner="gateway_mcp")
        except (TypeError, ValueError):
            return ActionOutcome("MCP invocation denied.", "DENY", None,
                                 "invalid MCP invocation request")
        authority, decision = self.gate.authorize(
            request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome("MCP invocation denied.", "DENY", None, reason)
        from isycode.gateway_mcp import invoke_gateway_tool
        try:
            result = await invoke_gateway_tool(tool_name, arguments, base_url=url)
        except (OSError, ValueError, RuntimeError) as exc:
            return ActionOutcome("MCP invocation failed.", "ERROR", None,
                                 f"Gateway MCP call failed ({type(exc).__name__})")
        try:
            result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return ActionOutcome("MCP invocation returned invalid output.", "ERROR", None,
                                 "Gateway MCP result is not JSON serializable")
        if len(result_text.encode("utf-8")) > 2_000_000:
            return ActionOutcome("MCP invocation output exceeded its display limit.", "ERROR", None,
                                 "result is larger than 2 MB")
        result_obj = result
        is_error = result_obj.get("isError") is True
        if is_error:
            return ActionOutcome(result_text[:MAX_OUTPUT_CHARS], "ERROR", None,
                                 "MCP tool returned isError")
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "mcp.invoke", request.digest,
            "ALLOW", "SUCCESS",
            hashlib.sha256(result_text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result_text):
            return ActionOutcome("MCP receipt failed verification.", "NOT_VERIFIABLE", None,
                                 "local request/result digest did not match")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("MCP receipt could not be persisted.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        visible = result_text[:MAX_OUTPUT_CHARS]
        if len(result_text) > MAX_OUTPUT_CHARS:
            visible += "\n… display truncated at 24,000 characters; receipt covers the full bounded result …"
        return ActionOutcome(visible, "ALLOW", receipt,
                             "one approved MCP tool invocation completed")


class GatewaySemanticOwner:
    """Perform one native read-only semantic operation through Gateway HTTP."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="gateway_semantic")

    def invoke(self, operation: str, payload: Mapping[str, Any], url: str,
               workspace_id: str, approval: ActionApproval | None) -> ActionOutcome:
        try:
            from isycode.semantic_gateway import SemanticGatewayClient, validate_semantic_payload
            from isycode.gateway_client import GatewayError

            normalized_payload = validate_semantic_payload(operation, payload)
            client = SemanticGatewayClient(base_url=url)
            expected_identity = os.environ.get("ISYCODE_GATEWAY_WORKSPACE_ID", "").strip()
            if not expected_identity or workspace_id != expected_identity:
                raise ValueError("workspace identity is not explicitly bound")
            request = ActionRequest(
                "gateway.semantic.read", self.root,
                GatewayMCPInvocationOwner.target_for(url).split("@", 1)[1],
                {"url": url, "operation": operation, "payload": normalized_payload,
                 "workspace_id": workspace_id}, execution_owner="gateway_semantic")
        except (OSError, ValueError, RuntimeError) as exc:
            return ActionOutcome("Semantic Gateway operation denied.", "DENY", None,
                                 f"invalid or unbound semantic request ({type(exc).__name__})")
        authority, decision = self.gate.authorize(
            request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome("Semantic Gateway operation denied.", "DENY", None, reason)
        try:
            # The same independently scoped Gateway key must report the ID
            # expected by ISyCode before any analysis request is dispatched.
            remote_identity = client.workspace_identity()
            if remote_identity != workspace_id:
                return ActionOutcome("Semantic Gateway operation denied.", "DENY", None,
                                     "Gateway workspace identity does not match the explicit local binding")
            result = client.call(operation, normalized_payload, workspace_id=workspace_id)
        except GatewayError as exc:
            return ActionOutcome("Semantic Gateway operation failed.", "ERROR", None,
                                 f"Gateway {exc.code} · {exc.message[:240]}")
        except (OSError, ValueError, RuntimeError) as exc:
            return ActionOutcome("Semantic Gateway operation failed.", "ERROR", None,
                                 f"Gateway request failed ({type(exc).__name__})")
        try:
            result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return ActionOutcome("Semantic search returned invalid output.", "ERROR", None,
                                 "result is not JSON serializable")
        if len(result_text.encode("utf-8")) > 2_000_000:
            return ActionOutcome("Semantic search output exceeded its limit.", "ERROR", None,
                                 "result is larger than 2 MB")
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result_text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result_text):
            return ActionOutcome("Semantic search receipt failed verification.",
                                 "NOT_VERIFIABLE", None,
                                 "local request/result digest did not match")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Semantic receipt could not be persisted.",
                                 "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        visible = result_text[:MAX_OUTPUT_CHARS]
        if len(result_text) > MAX_OUTPUT_CHARS:
            visible += "\n… display truncated at 24,000 characters; receipt covers the full bounded result …"
        return ActionOutcome(visible, "ALLOW", receipt,
                             f"one approved native Gateway {operation} completed; configured workspace IDs matched")


class LPSSymbolOwner:
    """Run a bounded Pyright workspace-symbol query through bubblewrap."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="lsp_symbols")

    async def search(self, server_id: str, query: str, approval: ActionApproval | None,
                     catalog: list[dict[str, Any]]) -> ActionOutcome:
        from isycode.lsp import discover_servers, pyright_workspace_symbols

        server = next((item for item in catalog if item.get("id") == server_id), None)
        current = next((item for item in discover_servers()
                        if item.get("id") == server_id), None)
        if (server is None or current is None or server.get("state") != "sandbox_ready"
                or any(server.get(key) != current.get(key) for key in (
                    "server_executable", "node_executable", "sandbox_executable"))):
            return ActionOutcome("LSP operation denied.", "DENY", None,
                                 "adapter catalog changed or is not sandbox-ready")
        # The language server can inspect the whole selected root. Require the
        # same explicit filesystem.read grant used by Files before mounting it.
        read_request = ActionRequest(
            "workspace.files.read", self.root, str(self.root), {"path": str(self.root)},
            execution_owner="lsp_symbols")
        _, read_decision = self.gate.authorize(read_request)
        if not read_decision.allowed:
            reason = "; ".join(check.reason for check in read_decision.checks if not check.passed)
            return ActionOutcome("LSP operation denied.", "DENY", None,
                                 "workspace.files.read grant required for the selected root: " + reason)
        try:
            request = ActionRequest(
                "lsp.start", self.root, server_id,
                {"operation": "workspace/symbol", "server_id": server_id,
                 "query": query, "workspace_root": str(self.root),
                 "executable": server["sandbox_executable"],
                 "server_executable": server["server_executable"],
                 "node_executable": server["node_executable"]},
                execution_owner="lsp_symbols")
        except (TypeError, ValueError):
            return ActionOutcome("LSP operation denied.", "DENY", None,
                                 "invalid LSP request")
        authority, decision = self.gate.authorize(
            request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome("LSP operation denied.", "DENY", None, reason)
        try:
            result = await pyright_workspace_symbols(self.root, query, server)
            result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError) as exc:
            return ActionOutcome("LSP request failed.", "ERROR", None,
                                 f"sandboxed LSP request failed ({type(exc).__name__})")
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "lsp.start", request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result_text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result_text):
            return ActionOutcome("LSP receipt failed verification.", "NOT_VERIFIABLE", None,
                                 "local request/result digest did not match")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("LSP receipt could not be persisted.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(result_text[:MAX_OUTPUT_CHARS], "ALLOW", receipt,
                             "LSP handshake and workspace/symbol response verified")


class LocalWorkspaceReadOwner:
    """Execute only list/read/name-search after grant and Sentinel ALLOW."""

    def __init__(self, root: Path, authority: WorkspaceAuthority):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.gate = ProductActionGate(self.root, authority, owner_id="workspace_read")

    def execute(self, action_id: str, arguments: dict[str, Any]) -> ActionOutcome:
        if action_id not in READ_ACTIONS:
            return ActionOutcome("Action unavailable.", "DENY", None,
                                 "action is not registered for this owner")
        if not isinstance(arguments, dict):
            return ActionOutcome("Malformed action arguments.", "DENY", None,
                                 "arguments must be an object")
        path_value = arguments.get("path", ".")
        if not isinstance(path_value, str) or len(path_value) > 4096:
            return ActionOutcome("Malformed action path.", "DENY", None,
                                 "path must be a bounded string")
        try:
            target = str(self._lexical_target(path_value))
        except (OSError, RuntimeError, ValueError) as exc:
            return ActionOutcome("ISySentinel denied this action.", "DENY", None,
                                 str(exc)[:300])
        request = ActionRequest(action_id, self.root, target, arguments,
                                execution_owner="workspace_read")
        try:
            authority, decision = self.gate.authorize(request)
        except Exception:
            return ActionOutcome("ISySentinel denied this action.", "DENY", None,
                                 "authorization evaluation failed")
        if not decision.allowed:
            reason = "; ".join(f"{item.name}: {item.reason}" for item in decision.checks
                                if not item.passed)
            return ActionOutcome("ISySentinel denied this action.", "DENY", None, reason)
        try:
            if action_id == "workspace.files.list":
                result = self._list(target)
            elif action_id in {"workspace.files.read", "workspace.context.inject"}:
                result = self._read(target)
            else:
                query = arguments.get("query", "")
                if not isinstance(query, str) or not query.strip() or len(query) > 256:
                    raise ValueError("search query must contain 1–256 characters")
                result = self._search(query.strip(), Path(target))
        except (OSError, ValueError) as exc:
            return ActionOutcome("Read action failed; no content was returned.",
                                 "ERROR", None, str(exc)[:300])
        if len(result) > MAX_OUTPUT_CHARS:
            result = result[:MAX_OUTPUT_CHARS] + "\n[output truncated]"
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), action_id, request.digest, "ALLOW", "SUCCESS",
            hashlib.sha256(result.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result):
            return ActionOutcome("Receipt verification failed; result blocked.",
                                 "NOT_VERIFIABLE", None, "local receipt did not match request/result")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Receipt persistence failed; result blocked.",
                                 "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(result, "ALLOW", receipt, "verified local read-only operation")

    def _lexical_target(self, path: str) -> Path:
        raw = Path(path).expanduser()
        candidate = raw if raw.is_absolute() else self.root / raw
        lexical = Path(os.path.abspath(candidate))
        if lexical != self.root and self.root not in lexical.parents:
            raise ValueError("path is outside the workspace root")
        return lexical

    def _list(self, target: str) -> str:
        directory = Path(target)
        descriptor = self._open_directory(directory)
        entries = []
        try:
            with os.scandir(descriptor) as iterator:
                for item in iterator:
                    if WorkspaceReadSystembility.is_sensitive_name(item.name) or item.is_symlink():
                        continue
                    kind = "directory" if item.is_dir(follow_symlinks=False) else "file"
                    entries.append({"name": item.name, "kind": kind})
                    if len(entries) >= 1000:
                        break
        finally:
            os.close(descriptor)
        entries.sort(key=lambda value: (value["kind"] != "directory", value["name"].casefold()))
        return json.dumps({"path": str(directory.relative_to(self.root) or "."),
                           "entries": entries}, ensure_ascii=False)

    def _read(self, target: str) -> str:
        path = Path(target)
        descriptor = self._open_file(path)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("selected path is not a regular file")
            if info.st_size > MAX_FILE_BYTES:
                raise ValueError("file exceeds the 128 KiB read limit")
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("file grew past the 128 KiB read limit")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("binary or non-UTF-8 files are not returned to chat") from exc
        return json.dumps({"path": str(path.relative_to(self.root)), "text": text},
                          ensure_ascii=False)

    def _search(self, query: str, start: Path) -> str:
        pending = [start]
        hits: list[dict[str, str]] = []
        visited = 0
        entries_seen = 0
        truncated = False
        folded = query.casefold()
        while pending:
            directory = pending.pop()
            descriptor = None
            try:
                descriptor = self._open_directory(directory)
                with os.scandir(descriptor) as iterator:
                    children = []
                    for child in iterator:
                        children.append(child)
                        entries_seen += 1
                        if entries_seen >= MAX_SCAN_ENTRIES:
                            truncated = True
                            break
            except OSError:
                continue
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            visited += 1
            if visited > 300 or truncated:
                truncated = True
                break
            for child in children:
                if WorkspaceReadSystembility.is_sensitive_name(child.name) or child.is_symlink():
                    continue
                path = directory / child.name
                if folded in child.name.casefold():
                    hits.append({
                        "path": str(path.relative_to(self.root)),
                        "kind": "directory" if child.is_dir(follow_symlinks=False) else "file",
                    })
                    if len(hits) >= 200:
                        truncated = True
                        break
                if child.is_dir(follow_symlinks=False):
                    pending.append(path)
            if truncated:
                break
        return json.dumps({"query": query, "matches": hits,
                           "directories_scanned": visited, "truncated": truncated},
                          ensure_ascii=False)

    def _open_directory(self, directory: Path) -> int:
        if os.name == "nt":
            raise OSError("descriptor-safe local reads are not available on this platform")
        relative = directory.relative_to(self.root)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.root, flags)
        try:
            for part in relative.parts:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _open_file(self, path: Path) -> int:
        if os.name == "nt":
            raise OSError("descriptor-safe local reads are not available on this platform")
        parent_fd = self._open_directory(path.parent)
        try:
            return os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                           dir_fd=parent_fd)
        finally:
            os.close(parent_fd)


__all__ = ["ActionOutcome", "ActionReceipt", "CHAT_WORKSPACE_TOOLS",
           "LocalWorkspaceReadOwner", "ProductActionGate", "ProviderNetworkSystembility",
           "RemoteReadSystembility", "SessionDeleteOwner", "SessionDeleteSystembility",
           "READ_ACTIONS", "TOOL_ACTIONS"]
