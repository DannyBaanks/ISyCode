"""Narrow local read-only action owner behind Authority and IsySentinel."""
from __future__ import annotations

import hashlib
import json
import os
import asyncio
import secrets
import shutil
import stat
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeGuard
from urllib.parse import urlsplit

from isycode.actions import ACTION_BY_ID
from isycode.action_audit import ActionAuditError, ActionAuditJournal
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.config import gateway_workspace_id
from isycode.security import (
    ActionRequest, AuthorityDecision, DecisionCheck, IsySentinel, SentinelDecision,
    SystembilityResult,
)
from isycode.workspace_authority import WorkspaceAuthority
from isycode.private_access import OwnedServeRoute
from isycode.tailscale import ServeRoute, _valid_gateway
from isycode.workspace_setup import state_root
from isycode.winfs import VerifiedFS, use_verified_fs
from isycode.sensitive_paths import is_sensitive_path_name


READ_ACTIONS = frozenset({
    "workspace.files.list", "workspace.files.read", "workspace.files.search",
    "workspace.context.inject",
})
CONFIG_READ_ACTIONS = frozenset({"workspace.config.read", "workspace.config.list"})
CONFIG_WRITE_ACTIONS = frozenset({"workspace.config.write"})
CONFIG_ACTIONS = CONFIG_READ_ACTIONS | CONFIG_WRITE_ACTIONS
CONFIG_OWNER_ID = "workspace_config"
CONFIG_MAX_BYTES = 1024 * 1024
CONFIG_JSON_MAX_BYTES = 64 * 1024
CONFIG_COMMAND_MAX_BYTES = 32 * 1024
CONFIG_COMMAND_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def workspace_config_path_allowed(root: Path, action_id: str, target: str) -> bool:
    """Exact internal config paths; generic workspace tools never use this exception."""
    try:
        canonical_root = Path(root).resolve(strict=True)
        raw = Path(target)
        lexical = Path(os.path.abspath(raw if raw.is_absolute() else canonical_root / raw))
        if lexical == canonical_root or canonical_root not in lexical.parents:
            return False
        relative = lexical.relative_to(canonical_root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return False
    command_file = (relative.endswith(".md")
                    and Path(relative).parent.as_posix() == ".isycode/commands"
                    and CONFIG_COMMAND_NAME_RE.fullmatch(Path(relative).stem) is not None)
    read_file = (relative == ".isycode/config.json"
                 or command_file
                 or relative == ".gitignore")
    write_file = (relative in {".isycode/config.json", ".gitignore"}
                  or command_file)
    valid = ((action_id == "workspace.config.read" and read_file)
             or (action_id == "workspace.config.list" and relative == ".isycode/commands")
             or (action_id == "workspace.config.write" and write_file))
    if not valid:
        return False
    current = canonical_root
    for part in Path(relative).parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return False
        if current == canonical_root / ".isycode" and not stat.S_ISDIR(info.st_mode):
            return False
        if current == canonical_root / ".isycode" / "commands" and not stat.S_ISDIR(info.st_mode):
            return False
    return True


def _workspace_config_request(action_id: str, root: Path, target: str,
                              arguments: dict[str, Any]) -> ActionRequest:
    return ActionRequest(action_id, root, target, arguments,
                         execution_owner="workspace_config")
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
        "name": "workspace_grep",
        "description": ("Find lines containing a literal text in authorized UTF-8 files (not a "
                        "regex); returns path, line number and the line. Skips sensitive, binary, "
                        "oversized and dependency folders."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Literal text to find; case-insensitive."},
            "path": {"type": "string", "description": "Workspace-relative folder or file; defaults to the workspace root."},
        }, "required": ["query"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "workspace_search", "description": "Search file and folder names, never file contents.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Text to find in names."},
            "path": {"type": "string", "description": "Workspace-relative folder path; defaults to the workspace root."},
        }, "required": ["query"], "additionalProperties": False},
    }},
]
CONTEXT_ACCESS_TOOL_NAME = "request_context_access"
CONTEXT_ACCESS_TOOL = {"type": "function", "function": {
    "name": CONTEXT_ACCESS_TOOL_NAME,
    "description": ("Pide permiso explícito para leer un único archivo de contexto .md o .txt "
                    "de un proyecto hermano directo. Abre un aviso; no concede acceso hasta "
                    "que el usuario lo apruebe."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Ruta absoluta a un archivo .md o .txt de un proyecto hermano directo."},
    }, "required": ["path"], "additionalProperties": False},
}}
TOOL_ACTIONS = {
    "workspace_list": "workspace.files.list",
    "workspace_read": "workspace.files.read",
    "workspace_search": "workspace.files.search",
    # Content search reveals exactly what reading does, so it is a read.
    "workspace_grep": "workspace.files.read",
}
GREP_SKIP_DIRECTORIES = frozenset({
    "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", "target", ".next",
})
GREP_MAX_FILES = 3000
GREP_MAX_BYTES = 24 * 1024 * 1024
GREP_MAX_MATCHES = 200
MAX_FILE_BYTES = 128 * 1024
MAX_WRITE_BYTES = 128 * 1024
WRITE_PARAMETER_KEYS = frozenset({"path", "before_sha256", "after_sha256", "size", "diff_sha256",
                                  "new_folders"})
DELETE_PARAMETER_KEYS = frozenset({"path", "before_sha256", "diff_sha256"})
MOVE_PARAMETER_KEYS = frozenset({"path", "to", "sha256", "new_folders", "undo_of"})
MAX_MOVE_BYTES = 16 * 1024 * 1024
FILE_CHANGE_ACTIONS = frozenset({"workspace.files.write", "workspace.files.restore",
                                 "workspace.files.delete", "workspace.files.move"})
RESTORE_PARAMETER_KEYS = frozenset({"path", "checkpoint_id", "current_sha256", "restore_sha256",
                                    "diff_sha256"})
# Workspace identity: a non-empty marker stops being a boundary, so the chat
# must never rewrite it.
WRITE_PROTECTED_NAMES = frozenset({".isyroot"})
MAX_OUTPUT_CHARS = 24_000
MAX_SCAN_ENTRIES = 6_000
# Sandboxed workspace commands (isycode.command_runner). The request binds the
# exact argv, resolved program, working folder, limits and the set of masked
# sensitive paths; nothing is expanded by a shell.
COMMAND_PARAMETER_KEYS = frozenset({
    "argv", "program", "cwd", "timeout_s", "network", "executable", "workspace_root",
    "masked_sha256", "masked_count", "max_output_bytes",
})
COMMAND_MAX_ARGS = 64
COMMAND_MAX_ARG_CHARS = 4096
COMMAND_MAX_ARGV_CHARS = 16_384
COMMAND_MAX_TIMEOUT_S = 600
COMMAND_MAX_OUTPUT_BYTES = 64 * 1024
COMMAND_SYSTEM_BIN_DIRS = ("/usr/local/bin", "/usr/bin", "/bin")
GIT_ACTIONS = frozenset({"git.status", "git.diff", "git.commit"})
PUBLISH_PARAMETER_KEYS = frozenset({"remote", "ref", "content_sha256"})
GIT_PARAMETER_KEYS = {
    "git.status": frozenset({"git", "workspace_root", "repo_path", "inspect_path"}),
    "git.diff": frozenset({"git", "workspace_root", "repo_path", "staged", "path"}),
    "git.commit": frozenset({"git", "workspace_root", "repo_path", "message", "paths", "diff_sha256"}),
}
MCP_SERVER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MCP_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MCP_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
MCP_START_KEYS = frozenset({"server", "argv", "executable", "cwd", "env_keys", "config_sha256"})
MCP_INVOKE_KEYS = frozenset({"server", "tool", "config_sha256", "arguments_sha256"})
LSP_DIAGNOSTIC_KEYS = frozenset({"operation", "server_id", "path", "text_sha256", "workspace_root",
                                 "executable", "server_executable", "node_executable"})
GIT_MAX_COMMIT_PATHS = 200
GIT_MAX_MESSAGE_CHARS = 4000

# Actions with no Secure execution owner are explicit denials in the owner
# binding check. A catalog addition is not enabled by adding a workspace grant.
EXPLICIT_DENY_ACTIONS = frozenset({
    "workspace.files.read_sensitive", "gateway.files.write", "oauth.authorize",
    "lsp.stop",
    "mobile.host.stop",
    "mobile.session.create", "mobile.session.cancel", "mobile.approval.respond",
    "bridge.connect", "bridge.send", "bridge.lease.claim", "bridge.lease.release",
    "bridge.wake", "l1.create", "l1.validate", "l1.test", "l1.activate",
    "l1.disable", "l1.rollback",
    "desktop.file_picker", "bridge.peek", "lsp.discover", "mobile.session.read",
})


@dataclass(frozen=True)
class OwnerActionVariant:
    """Parameter discriminator for intentionally shared action identifiers."""

    action_id: str
    owner_id: str
    required_parameters: tuple[tuple[str, Any], ...]
    absent_parameters: tuple[str, ...] = ()

    def matches(self, request: ActionRequest) -> bool:
        parameters = request.parameters
        return (
            request.action_id == self.action_id
            and request.execution_owner == self.owner_id
            and all(parameters.get(key) == value for key, value in self.required_parameters)
            and all(key not in parameters for key in self.absent_parameters)
        )


OWNER_ACTION_VARIANTS = (
    OwnerActionVariant(
        "broker.start", "broker_provision",
        (("operation", "start"),), ("managed_existing",),
    ),
    OwnerActionVariant(
        "broker.start", "broker_management",
        (("operation", "start"), ("managed_existing", True)),
    ),
)

OWNER_REQUIRED_SYSTEMBILITIES = {
    "workspace_read": frozenset({"WorkspaceReadBoundary"}),
    "workspace_write": frozenset({"WorkspaceWriteBoundary"}),
    CONFIG_OWNER_ID: frozenset({"WorkspaceReadBoundary", "WorkspaceWriteBoundary",
                                "WorkspaceConfigBoundary"}),
    "provider_auth": frozenset({"ProviderAuthBoundary"}),
    "provider_network": frozenset({"ProviderNetworkBoundary"}),
    "web_fetch": frozenset({"RemoteReadBoundary"}),
    "remote_catalog": frozenset({"RemoteReadBoundary"}),
    "session_delete": frozenset({"SessionDeleteBoundary"}),
    "chat_sessions": frozenset({"SessionStoreBoundary"}),
    "credentials": frozenset({"CredentialBoundary"}),
    "credential_use": frozenset({"CredentialBoundary"}),
    "gateway_mcp": frozenset({"MCPInvocationBoundary"}),
    "gateway_semantic": frozenset({"GatewaySemanticBoundary"}),
    "lsp_symbols": frozenset({"WorkspaceReadBoundary", "LSPProcessBoundary"}),
    "broker_preview": frozenset({"WorkspaceReadBoundary", "BrokerRecipeBoundary"}),
    "broker_provision": frozenset({
        "WorkspaceReadBoundary", "BrokerProvisionBoundary", "BrokerRegistryBoundary",
    }),
    "broker_management": frozenset({"BrokerRegistryBoundary"}),
    "tailscale_read": frozenset({"TailscaleExecutableBoundary", "TailscaleGatewayBoundary"}),
    "tailscale_package_install": frozenset({"TailscalePackageBoundary"}),
    "tailscale_login": frozenset({"TailscaleExecutableBoundary"}),
    "tailscale_serve": frozenset({"TailscaleExecutableBoundary", "TailscaleGatewayBoundary",
                                   "TailscalePrivateServeBoundary"}),
    "mobile_host": frozenset({"MobileHostBoundary"}),
    "workspace_command": frozenset({"CommandProcessBoundary"}),
    "workspace_git": frozenset({"GitBoundary"}),
    "workspace_publish": frozenset({"PublishBoundary"}),
    "mcp_local": frozenset({"LocalMCPBoundary"}),
    "clipboard": frozenset({"ClipboardBoundary"}),
    "bridge_presence": frozenset({"BridgePresenceBoundary"}),
}


# Explicit closed registry. Requests still bind the selected owner in their digest;
# there is no default or fallback owner. Shared file reads are helper requests
# nested inside four separately bound owners and are reported as such.
OWNER_ACTIONS = {
    "workspace_read": READ_ACTIONS,
    "workspace_write": FILE_CHANGE_ACTIONS,
    CONFIG_OWNER_ID: CONFIG_ACTIONS,
    "provider_auth": frozenset({"provider.authenticate"}),
    "provider_network": frozenset({"provider.request"}),
    "web_fetch": frozenset({"web.fetch"}),
    "remote_catalog": frozenset({"gateway.files.read", "mcp.discover", "catalog.external.read"}),
    "session_delete": frozenset({"session.delete"}),
    "chat_sessions": frozenset({"session.create", "session.resume"}),
    "credentials": frozenset({"credentials.add", "credentials.revoke"}),
    "credential_use": frozenset({"credentials.use"}),
    "gateway_mcp": frozenset({"mcp.invoke"}),
    "gateway_semantic": frozenset({"gateway.semantic.read"}),
    "lsp_symbols": frozenset({"workspace.files.read", "lsp.start", "lsp.diagnostics"}),
    "broker_preview": frozenset({"workspace.files.read", "broker.preview"}),
    "broker_provision": frozenset({"workspace.files.read", "broker.build", "broker.start"}),
    "broker_management": frozenset({"broker.health", "broker.logs", "broker.start",
                                      "broker.stop", "broker.remove"}),
    "tailscale_read": frozenset({"tailscale.inspect"}),
    "tailscale_package_install": frozenset({"tailscale.install.prepare", "tailscale.install.stage", "tailscale.install"}),
    "tailscale_login": frozenset({"tailscale.login"}),
    "tailscale_serve": frozenset({"tailscale.serve.enable", "tailscale.serve.disable"}),
    "mobile_host": frozenset({"mobile.host.start", "mobile.pair", "mobile.pair.issue"}),
    "workspace_command": frozenset({"workspace.command.run"}),
    "workspace_git": GIT_ACTIONS,
    "workspace_publish": frozenset({"git.push"}),
    "mcp_local": frozenset({"mcp.local.start", "mcp.local.invoke"}),
    "clipboard": frozenset({"clipboard.copy", "clipboard.paste"}),
    "bridge_presence": frozenset({"bridge.agents"}),
}


@dataclass(frozen=True)
class TailscaleAuthorityFacts:
    """Trusted, immutable adapter observations supplied by the concrete owner.

    Request parameters alone cannot establish executable, route, or ownership
    identity. The owner must obtain these facts from its read adapter and state
    store immediately before authorization; an absent fact denies.
    """

    cli_executable: str | None = None
    package_manager: str | None = None
    os_id: str | None = None
    os_codename: str | None = None
    gateway_url: str | None = None
    gateway_port: int | None = None
    route_id: str | None = None
    proposed_route: ServeRoute | None = None
    live_routes: tuple[ServeRoute, ...] | None = None
    serve_inventory_complete: bool = False
    owned_route: OwnedServeRoute | None = None
    serve_digest: str | None = None


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
        if request.action_id not in READ_ACTIONS | CONFIG_READ_ACTIONS:
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
        if (any(self.is_sensitive_name(part) for part in resolved.relative_to(self.root).parts)
                and not (request.execution_owner == CONFIG_OWNER_ID
                         and request.action_id in CONFIG_READ_ACTIONS
                         and workspace_config_path_allowed(self.root, request.action_id,
                                                           str(lexical)))):
            return SystembilityResult(self.name, False, "sensitive paths are not available to chat tools")
        return SystembilityResult(self.name, True, "read-only target is inside the workspace")

    @staticmethod
    def is_sensitive_name(name: str) -> bool:
        return is_sensitive_path_name(name)


class WorkspaceWriteSystembility:
    """Allow one bounded, non-sensitive text replacement bound to its exact diff."""

    name = "WorkspaceWriteBoundary"

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in FILE_CHANGE_ACTIONS | CONFIG_WRITE_ACTIONS:
            return SystembilityResult(self.name, True, "not applicable to this action")
        if request.workspace_root != self.root:
            return SystembilityResult(self.name, False, "request workspace does not match owner")
        params = request.parameters

        def digest(value: object, *, absent: bool = False) -> bool:
            return isinstance(value, str) and (
                (absent and value == "absent") or re.fullmatch(r"[0-9a-f]{64}", value) is not None)

        def new_folders_valid(folders: object, path_value: object) -> bool:
            ancestors = ({parent.as_posix() for parent in Path(path_value).parents}
                         if isinstance(path_value, str) else set())
            config_commands_extra = (request.execution_owner == CONFIG_OWNER_ID
                                     and request.action_id in CONFIG_WRITE_ACTIONS
                                     and path_value == ".isycode/config.json")
            return (isinstance(folders, tuple) and len(folders) <= 8
                    and all(isinstance(item, str)
                            and (item in ancestors or
                                 (config_commands_extra and item == ".isycode/commands"))
                            and item != "."
                            and (not any(WorkspaceReadSystembility.is_sensitive_name(part)
                                         for part in Path(item).parts)
                                 or (request.execution_owner == CONFIG_OWNER_ID
                                     and item in {".isycode", ".isycode/commands"}))
                            for item in folders))

        if request.action_id == "workspace.files.restore":
            if (set(params) != RESTORE_PARAMETER_KEYS
                    or not isinstance(params.get("checkpoint_id"), str)
                    or re.fullmatch(r"ckpt_[0-9]{13}_[0-9a-f]{8}", params["checkpoint_id"]) is None
                    or not digest(params.get("current_sha256"), absent=True)
                    or not digest(params.get("restore_sha256"), absent=True)
                    or params.get("current_sha256") == params.get("restore_sha256")
                    or not digest(params.get("diff_sha256"))):
                return SystembilityResult(self.name, False, "undo request shape is not the reviewed diff")
        elif request.action_id == "workspace.files.delete":
            if (set(params) != DELETE_PARAMETER_KEYS or not digest(params.get("before_sha256"))
                    or not digest(params.get("diff_sha256"))):
                return SystembilityResult(self.name, False, "delete request shape is not the reviewed one")
        elif request.action_id == "workspace.files.move":
            destination = params.get("to")
            undo_of = params.get("undo_of")
            if (set(params) != MOVE_PARAMETER_KEYS or not digest(params.get("sha256"))
                    or not command_relative_path_valid(destination)
                    or destination == params.get("path")
                    or Path(destination).name.casefold() in WRITE_PROTECTED_NAMES
                    or not new_folders_valid(params.get("new_folders"), destination)
                    or not isinstance(undo_of, str)
                    or (undo_of and re.fullmatch(r"ckpt_[0-9]{13}_[0-9a-f]{8}", undo_of) is None)):
                return SystembilityResult(self.name, False, "move request shape is not the reviewed one")
            current = self.root
            for part in destination.split("/"):
                current = current / part
                try:
                    if stat.S_ISLNK(current.lstat().st_mode):
                        return SystembilityResult(self.name, False, "symlink traversal is denied")
                except FileNotFoundError:
                    break
                except OSError:
                    return SystembilityResult(self.name, False, "destination metadata is unavailable")
        else:
            size = params.get("size")
            folders = params.get("new_folders")
            if set(params) != WRITE_PARAMETER_KEYS:
                return SystembilityResult(self.name, False, "write request shape is not the reviewed diff")
            max_bytes = (CONFIG_MAX_BYTES if request.execution_owner == CONFIG_OWNER_ID
                         and request.action_id in CONFIG_WRITE_ACTIONS
                         and params.get("path") == ".gitignore" else MAX_WRITE_BYTES)
            if (not digest(params.get("before_sha256"), absent=True)
                    or not digest(params.get("after_sha256"))
                    or not digest(params.get("diff_sha256"))
                    or type(size) is not int or not 0 <= size <= max_bytes):
                return SystembilityResult(self.name, False, "write digests or size are invalid")
            if not new_folders_valid(folders, params.get("path")):
                return SystembilityResult(self.name, False, "new folders must be the file's own parents")
        lexical = Path(os.path.abspath(request.target or ""))
        if self.root not in lexical.parents:
            return SystembilityResult(self.name, False, "write target must be a file inside the workspace")
        relative = lexical.relative_to(self.root)
        if params.get("path") != relative.as_posix():
            return SystembilityResult(self.name, False, "write path does not match its target")
        if (any(WorkspaceReadSystembility.is_sensitive_name(part) for part in relative.parts)
                and not (request.execution_owner == CONFIG_OWNER_ID
                         and request.action_id in CONFIG_WRITE_ACTIONS
                         and workspace_config_path_allowed(self.root, request.action_id,
                                                           str(lexical)))):
            return SystembilityResult(self.name, False, "sensitive paths cannot be written")
        if relative.name.casefold() in WRITE_PROTECTED_NAMES:
            return SystembilityResult(self.name, False, "workspace identity markers cannot be written")
        current = self.root
        for part in relative.parts:
            current = current / part
            try:
                if stat.S_ISLNK(current.lstat().st_mode):
                    return SystembilityResult(self.name, False, "symlink traversal is denied")
            except FileNotFoundError:
                break
            except OSError:
                return SystembilityResult(self.name, False, "target metadata is unavailable")
        return SystembilityResult(self.name, True, "one reviewed file change inside the workspace")


class WorkspaceConfigBoundary:
    """Keep internal config access limited to its non-sensitive, exact paths."""

    name = "WorkspaceConfigBoundary"

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.execution_owner != CONFIG_OWNER_ID:
            return SystembilityResult(self.name, True, "not applicable to this owner")
        if (request.workspace_root != self.root or request.action_id not in CONFIG_ACTIONS
                or not workspace_config_path_allowed(self.root, request.action_id,
                                                     request.target)):
            return SystembilityResult(self.name, False,
                                      "internal config owner is restricted to approved config paths")
        if request.action_id in CONFIG_WRITE_ACTIONS:
            path = Path(request.target)
            expected = path.relative_to(self.root).as_posix()
            if request.parameters.get("path") != expected:
                return SystembilityResult(self.name, False, "config write path does not match target")
            limit = (CONFIG_JSON_MAX_BYTES if expected == ".isycode/config.json"
                     else CONFIG_COMMAND_MAX_BYTES if expected.startswith(".isycode/commands/")
                     else CONFIG_MAX_BYTES)
            size = request.parameters.get("size")
            if type(size) is not int or not 0 <= size <= limit:
                return SystembilityResult(self.name, False,
                                          "internal config file exceeds its path-specific size limit")
        return SystembilityResult(self.name, True, "internal config path is within the workspace boundary")


def command_argv_valid(argv: object) -> TypeGuard[tuple[str, ...]]:
    """A bounded, NUL-free argv tuple; no shell ever interprets it."""
    return (isinstance(argv, tuple) and 1 <= len(argv) <= COMMAND_MAX_ARGS
            and all(isinstance(item, str) and "\x00" not in item
                    and len(item) <= COMMAND_MAX_ARG_CHARS for item in argv)
            and bool(argv[0]) and sum(len(item) for item in argv) <= COMMAND_MAX_ARGV_CHARS)


def command_relative_path_valid(value: object, *, allow_root: bool = False) -> TypeGuard[str]:
    """A workspace-relative POSIX path with no traversal or sensitive part."""
    if not isinstance(value, str) or not value or len(value) > 1024 or "\x00" in value:
        return False
    if value == ".":
        return allow_root
    if value.startswith("/") or "\\" in value:
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."}
               and not WorkspaceReadSystembility.is_sensitive_name(part) for part in parts)


def sandbox_program_valid(program: object, argv0: str) -> bool:
    """A system program from a fixed bin folder, or a workspace file, named like argv[0]."""
    if not isinstance(program, str) or Path(program).name != Path(argv0).name:
        return False
    if program.startswith("/workspace/"):
        return command_relative_path_valid(program[len("/workspace/"):])
    parent, _, name = program.rpartition("/")
    return parent in COMMAND_SYSTEM_BIN_DIRS and command_relative_path_valid(name)


class CommandProcessSystembility:
    """Allow one reviewed argv inside the bubblewrap workspace sandbox."""

    name = "CommandProcessBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id != "workspace.command.run":
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        if set(params) not in (COMMAND_PARAMETER_KEYS, COMMAND_PARAMETER_KEYS | {"scope"}):
            return SystembilityResult(self.name, False, "command request shape is not the reviewed one")
        argv = params.get("argv")
        if not command_argv_valid(argv):
            return SystembilityResult(self.name, False, "command arguments are invalid")
        if not sandbox_program_valid(params.get("program"), argv[0]) or request.target != params["program"]:
            return SystembilityResult(self.name, False, "program must be a system or workspace executable")
        timeout = params.get("timeout_s")
        count = params.get("masked_count")
        if "scope" in params and not command_relative_path_valid(params["scope"], allow_root=True):
            return SystembilityResult(self.name, False, "command staging scope is invalid")
        if (not command_relative_path_valid(params.get("cwd"), allow_root=True)
                or type(timeout) is not int or not 1 <= timeout <= COMMAND_MAX_TIMEOUT_S
                or params.get("network") != "denied"
                or params.get("max_output_bytes") != COMMAND_MAX_OUTPUT_BYTES
                or type(count) is not int or count < 0
                or not isinstance(params.get("masked_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", params["masked_sha256"]) is None
                or params.get("workspace_root") != str(request.workspace_root)):
            return SystembilityResult(self.name, False, "command limits or sandbox facts are invalid")
        try:
            sandbox = str(Path(shutil.which("bwrap") or "").resolve(strict=True))
        except (OSError, RuntimeError):
            return SystembilityResult(self.name, False, "the command sandbox is unavailable")
        if params.get("executable") != sandbox:
            return SystembilityResult(self.name, False, "command must run through the bubblewrap sandbox")
        return SystembilityResult(
            self.name, True,
            "one reviewed argv in a sandbox: only the workspace is writable, sensitive paths are "
            "masked and socket syscalls are denied")


class GitSystembility:
    """Allow git status/diff/commit only for the workspace repository and a system git."""

    name = "GitBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in GIT_ACTIONS:
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        expected = GIT_PARAMETER_KEYS[request.action_id]
        valid_shape = (set(params) == expected
                       or (request.action_id == "git.status"
                           and set(params) == expected - {"inspect_path"}))
        if not valid_shape:
            return SystembilityResult(self.name, False, "git request shape is not the reviewed one")
        repo_path = params.get("repo_path", ".")
        repo_valid = (isinstance(repo_path, str) and
                      (repo_path == "." or
                       (command_relative_path_valid(repo_path)
                        and len(Path(repo_path).parts) == 1
                        and not repo_path.startswith("."))))
        if (not repo_valid or request.target != str(request.workspace_root)
                or params.get("workspace_root") != str(request.workspace_root)):
            return SystembilityResult(self.name, False, "git request must target one direct workspace repository")
        if not sandbox_program_valid(params.get("git"), "git"):
            return SystembilityResult(self.name, False, "git must be the system git executable")
        if request.action_id == "git.diff":
            if (type(params.get("staged")) is not bool
                    or not command_relative_path_valid(params.get("path"), allow_root=True)):
                return SystembilityResult(self.name, False, "git diff scope is invalid")
        elif request.action_id == "git.commit":
            message = params.get("message")
            paths = params.get("paths")
            if (not isinstance(message, str) or not message.strip() or "\x00" in message
                    or len(message) > GIT_MAX_MESSAGE_CHARS):
                return SystembilityResult(self.name, False, "commit message is invalid")
            if (not isinstance(paths, tuple) or not 1 <= len(paths) <= GIT_MAX_COMMIT_PATHS
                    or len(set(paths)) != len(paths)
                    or not all(command_relative_path_valid(path) for path in paths)):
                return SystembilityResult(self.name, False, "commit paths must be non-sensitive workspace files")
            digest = params.get("diff_sha256")
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                return SystembilityResult(self.name, False, "commit must be bound to its reviewed diff")
        elif params.get("inspect_path") is not None:
            if params.get("inspect_path") != ".isycode":
                return SystembilityResult(self.name, False,
                                          "git tracked-path inspection is limited to .isycode")
        return SystembilityResult(
            self.name, True,
            "workspace repository only; repository-defined programs and hooks are refused")


def _publish_remote_exact(remote: str) -> bool:
    """One https URL with a host and a repository path, and nothing else."""
    parsed = urlsplit(remote)
    return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path not in {"", "/"} and ".." not in parsed.path.split("/"))


class PublishSystembility:
    """One https remote, one ref and one content digest. There is no other publication."""

    name = "PublishBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id != "git.push":
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        remote = params.get("remote") if isinstance(params, Mapping) else None
        ref = params.get("ref") if isinstance(params, Mapping) else None
        digest = params.get("content_sha256") if isinstance(params, Mapping) else None
        if (not isinstance(params, Mapping) or set(params) != PUBLISH_PARAMETER_KEYS
                or not isinstance(remote, str) or remote != request.target
                or not _publish_remote_exact(remote)):
            return SystembilityResult(self.name, False,
                                      "publication remote is not one exact https URL")
        if not isinstance(ref, str) or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", ref) is None:
            return SystembilityResult(self.name, False, "publication ref is invalid")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return SystembilityResult(self.name, False, "publication content digest is invalid")
        return SystembilityResult(
            self.name, True, "one https remote, one ref and one content digest")


class LocalMCPSystembility:
    """Bind a local MCP start to its reviewed command and a call to its reviewed arguments."""

    name = "LocalMCPBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in {"mcp.local.start", "mcp.local.invoke"}:
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters

        def digest(value: object) -> bool:
            return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

        server = params.get("server")
        if (not isinstance(server, str) or not MCP_SERVER_NAME_RE.match(server)
                or request.target != server or not digest(params.get("config_sha256"))):
            return SystembilityResult(self.name, False, "MCP server identity is invalid")
        if request.action_id == "mcp.local.start":
            env_keys = params.get("env_keys")
            executable = params.get("executable")
            if (set(params) != MCP_START_KEYS or not command_argv_valid(params.get("argv"))
                    or not isinstance(executable, str) or not executable.startswith("/")
                    or params.get("cwd") != str(request.workspace_root)
                    or not isinstance(env_keys, tuple)
                    or not all(isinstance(key, str) and MCP_ENV_NAME_RE.match(key)
                               for key in env_keys)):
                return SystembilityResult(self.name, False, "MCP start request is not the reviewed one")
            return SystembilityResult(self.name, True,
                                      "reviewed command from the user's MCP config, in the workspace")
        tool = params.get("tool")
        if (set(params) != MCP_INVOKE_KEYS or not isinstance(tool, str)
                or not MCP_TOOL_NAME_RE.match(tool) or not digest(params.get("arguments_sha256"))):
            return SystembilityResult(self.name, False, "MCP call request is not the reviewed one")
        return SystembilityResult(self.name, True, "one reviewed tool call to a running local server")


class ClipboardSystembility:
    """One bounded copy, described only by source, size and digest."""

    name = "ClipboardBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id == "clipboard.paste":
            valid = (request.target == "clipboard" and request.parameters == {"source": "user_paste", "max_bytes": 8 * 1024 * 1024})
            return SystembilityResult(self.name, valid, "bounded user-initiated clipboard read" if valid else "clipboard paste shape is invalid")
        if request.action_id != "clipboard.copy":
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        size, digest = params.get("size"), params.get("sha256")
        valid = (set(params) == {"source", "size", "sha256"} and request.target == "clipboard"
                 and params.get("source") in {"selection", "file_path"}
                 and type(size) is int and 1 <= size <= 1024 * 1024
                 and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None)
        return SystembilityResult(self.name, valid,
                                  "user-initiated copy; the text itself is never recorded" if valid
                                  else "clipboard request shape is invalid")


class ProviderAuthSystembility:
    """Pure validation of a bounded official connector identity, no token access."""
    name = "ProviderAuthBoundary"

    @staticmethod
    def identity_valid(identity):
        from isycode.provider_auth import connector_identity, connector_home
        try:
            executable = identity.get("executable")
            path = Path(executable).resolve(strict=True)
            if str(path) != executable or not path.is_file() or not os.access(path, os.X_OK):
                return False
            expected = connector_identity(executable)
            if set(identity) != set(expected):
                return False
            if any(identity[key] != value for key, value in expected.items() if key != "hosts"):
                return False
            if tuple(identity.get("hosts", ())) != tuple(expected["hosts"]):
                return False
            home = connector_home()
            if home.resolve(strict=False) != home:
                return False
            return not any(p.is_symlink() for p in (home, *home.parents))
        except (OSError, TypeError, ValueError, AttributeError):
            return False

    def evaluate(self, request, authority):
        if request.action_id != "provider.authenticate":
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        valid = (request.target == "chatgpt" and set(params) == {"operation", "method", "connector"}
                 and params.get("operation") in {"login", "logout"}
                 and params.get("method") in {"browser", "device"}
                 and self.identity_valid(params.get("connector", {})))
        return SystembilityResult(self.name, valid, "authentication binds official executable, private keyring and fixed hosts")


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
        if request.parameters.get("provider") == "chatgpt":
            from isycode.provider_auth import CHATGPT_ENDPOINT
            if url != CHATGPT_ENDPOINT or not ProviderAuthSystembility.identity_valid(request.parameters.get("connector", {})):
                return SystembilityResult(self.name, False, "subscription inference requires a bound official connector")
        return SystembilityResult(self.name, True, "provider endpoint is secure and host-bound")


class RemoteReadSystembility:
    """Bound read-only catalog/health requests to one explicitly granted URL host."""

    name = "RemoteReadBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        spec = ACTION_BY_ID.get(request.action_id)
        if spec is None or not spec.effect.startswith("network") or request.action_id == "provider.request":
            return SystembilityResult(self.name, True, "not applicable to this action")
        if request.action_id == "mobile.host.start":
            return SystembilityResult(self.name, True,
                                      "local listener is checked by the Mobile Host boundary")
        if request.action_id not in {"gateway.files.read", "gateway.semantic.read",
                                     "mcp.discover", "catalog.external.read", "web.fetch"}:
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


class CredentialBoundarySystembility:
    """Save or revoke one key for one known service; the secret is never in the request."""

    name = "CredentialBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in {"credentials.add", "credentials.revoke", "credentials.use"}:
            return SystembilityResult(self.name, True, "not applicable to this action")
        from isycode.providers import PRESETS  # local import: providers loads lazily

        params = request.parameters
        service = params.get("service")
        known = isinstance(service, str) and (service in PRESETS or service == "isyco-gateway")
        if request.action_id == "credentials.add":
            labels_ok = all(
                isinstance(params.get(key), str) and 1 <= len(params[key]) <= 96
                and params[key] == " ".join(params[key].split())
                and all(char.isprintable() for char in params[key])
                for key in ("name", "purpose"))
            valid = (set(params) == {"service", "name", "purpose"} and known
                     and request.target == service and labels_ok)
        elif request.action_id == "credentials.use":
            valid = (set(params) == {"service", "consumer"} and known
                     and request.target == service
                     and params.get("consumer") in {"provider.request", "gateway", "mcp", "semantic"})
        else:
            key_id = params.get("key_id")
            valid = (set(params) == {"key_id", "service"} and known
                     and request.target == service and isinstance(key_id, str)
                     and re.fullmatch(r"cred_[a-f0-9]{16}", key_id) is not None)
        return SystembilityResult(self.name, valid,
                                  "one key for one known service; no secret in the request")


class SessionStoreSystembility:
    """Bind transcript writes and reads to one session id and message digest."""

    name = "SessionStoreBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in {"session.create", "session.resume"}:
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        session_id = params.get("session_id")
        valid_id = isinstance(session_id, str) and re.fullmatch(r"[0-9a-f]{32}", session_id) is not None
        if request.action_id == "session.create":
            size = params.get("size")
            fields = set(params) - {"state_sha256"}
            state_digest = params.get("state_sha256", "0" * 64)
            valid = (fields == {"operation", "session_id", "role", "content_sha256", "size"}
                     and params.get("operation") in {"create", "append"}
                     and valid_id and request.target == session_id
                     and params.get("role") in {"user", "assistant"}
                     and isinstance(params.get("content_sha256"), str)
                     and re.fullmatch(r"[0-9a-f]{64}", params["content_sha256"]) is not None
                     and type(size) is int and 0 <= size <= 1_000_000)
            valid = valid and isinstance(state_digest, str) and re.fullmatch(r"[0-9a-f]{64}", state_digest) is not None
            if params.get("operation") in {"rename", "auto_title", "fork", "import", "state"}:
                source = params.get("source_id")
                valid = (set(params) == {"operation", "session_id", "content_sha256", "size", "source_id"}
                         and valid_id and request.target == session_id
                         and isinstance(params.get("content_sha256"), str)
                         and re.fullmatch(r"[0-9a-f]{64}", params["content_sha256"]) is not None
                         and type(size) is int and 0 <= size <= 1_000_000
                         and isinstance(source, str)
                         and (source in {"", session_id} if params["operation"] == "state"
                              else source == "" if params["operation"] == "import"
                              else re.fullmatch(r"[0-9a-f]{32}", source) is not None)
                         and (source == session_id if params["operation"] in {"rename", "auto_title"} else True))
            return SystembilityResult(self.name, valid,
                                      "one bounded message bound to one local transcript")
        if params.get("operation") == "list":
            valid = params == {"operation": "list"} and request.target == "sessions"
        elif params.get("operation") in {"divergence_detected", "divergence_forked",
                                         "divergence_reloaded", "divergence_unsaved"}:
            # Evidence that two continuities of one transcript diverged and what the
            # user chose: ids and sha256 revisions only, never transcript content.
            def revision(value) -> bool:
                return isinstance(value, str) and (
                    value == "" or re.fullmatch(r"[0-9a-f]{64}", value) is not None)
            keys = {"operation", "session_id", "expected_revision", "current_revision"}
            forked = params["operation"] == "divergence_forked"
            valid = (set(params) == (keys | {"fork_id"} if forked else keys)
                     and valid_id and request.target == session_id
                     and revision(params.get("expected_revision"))
                     and revision(params.get("current_revision"))
                     and (not forked or (isinstance(params.get("fork_id"), str)
                                         and re.fullmatch(r"[0-9a-f]{32}", params["fork_id"]) is not None)))
        else:
            valid = (set(params) == {"operation", "session_id"}
                     and params.get("operation") == "load"
                     and valid_id and request.target == session_id)
        return SystembilityResult(self.name, valid, "list or load one local transcript")


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
        try:
            expected_identity = gateway_workspace_id(request.workspace_root)
        except (OSError, RuntimeError, ValueError):
            return SystembilityResult(self.name, False, "workspace root cannot be resolved for Gateway binding")
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
    """Allow only catalogued workspace-symbol adapters inside bubblewrap."""

    name = "LSPProcessBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in {"lsp.start", "lsp.diagnostics"}:
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
        if request.action_id == "lsp.diagnostics":
            params = request.parameters
            digest = params.get("text_sha256")
            if (server["id"] != "pyright" or set(params) != LSP_DIAGNOSTIC_KEYS or request.target != server["id"]
                    or params.get("operation") != "textDocument/publishDiagnostics"
                    or params.get("executable") != sandbox
                    or params.get("server_executable") != server["server_executable"]
                    or params.get("node_executable") != server["node_executable"]
                    or params.get("workspace_root") != str(request.workspace_root)
                    or not command_relative_path_valid(params.get("path"))
                    or not str(params.get("path")).endswith(".py")
                    or not isinstance(digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
                return SystembilityResult(self.name, False, "LSP diagnostics request does not match the sandbox owner")
            return SystembilityResult(
                self.name, True,
                "one Python file checked by a read-only, network-denied language server")
        if (request.target != server["id"]
                or request.parameters.get("operation") != "workspace/symbol"
                or request.parameters.get("executable") != sandbox
                or request.parameters.get("server_executable") != server["server_executable"]
                or request.parameters.get("node_executable") != server["node_executable"]
                or request.parameters.get("workspace_root") != str(request.workspace_root)
                or request.parameters.get("runtime_executable", "") != server.get("runtime_executable", "")):
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


_TAILSCALE_ACTIONS = frozenset({"tailscale.inspect", "tailscale.install.prepare", "tailscale.install.stage", "tailscale.install", "tailscale.login",
                                "tailscale.serve.enable", "tailscale.serve.disable"})
_TAILSCALE_SERVE_ACTIONS = frozenset({"tailscale.serve.enable", "tailscale.serve.disable"})
_TAILSCALE_SERVE_KEYS = frozenset({"executable", "gateway_url", "gateway_port", "route_id",
                                   "route_host", "route_path", "route_target", "serve_digest",
                                   "serve_argv", "serve_delta_digest", "mode", "funnel"})
_SUPPORTED_TAILSCALE_APT = {
    "ubuntu": frozenset({"focal", "jammy", "noble"}),
    "debian": frozenset({"bullseye", "bookworm", "trixie"}),
}


def tailscale_stage_operations(stage_directory: str,
                               artifacts: tuple[tuple[str, str, int, str], ...]
                               ) -> tuple[tuple[str, ...], ...]:
    """All fixed privileged argv allowed by one stage approval."""
    stage = Path(stage_directory)
    commands: list[tuple[str, ...]] = []

    def add(*argv: str) -> None:
        command = ("/usr/bin/pkexec", *argv)
        if command not in commands:
            commands.append(command)

    metadata = "--printf=%u\t%a\t%F\t%h\t%s"
    for directory in (Path("/var"), Path("/var/lib")):
        add("/usr/bin/stat", metadata, "--", str(directory))
    for directory in (stage.parent.parent, stage.parent, stage,
                      stage / "lists", stage / "cache",
                      stage / "lists" / "partial", stage / "cache" / "partial"):
        add("/usr/bin/stat", "--printf=%F", "--", str(directory))
        add("/usr/bin/install", "-d", "-m", "0700", "--", str(directory))
        add("/usr/bin/stat", metadata, "--", str(directory))
    for relative, source, size, _ in artifacts:
        target = stage / relative
        add("/usr/bin/dd", f"if={source}", f"of={target}",
            "iflag=count_bytes", f"count={size + 1}",
            "oflag=excl", "conv=fsync", "status=none")
        add("/usr/bin/chmod", "0400", "--", str(target))
        add("/usr/bin/stat", metadata, "--", str(target))
        add("/usr/bin/sha256sum", "--binary", "--", str(target))
    add("/usr/bin/chmod", "0000", "--", str(stage))
    return tuple(commands)


def tailscale_serve_delta_digest(action_id: str, serve_digest: str,
                                 route: ServeRoute,
                                 argv: tuple[str, ...]) -> str:
    """Digest the exact pre-state, private route identity, and fixed CLI operation."""
    payload = (action_id, serve_digest,
               (route.host, route.path, route.target, route.private), argv)
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _canonical_executable_identity(value: object, expected_name: str) -> bool:
    """Check the canonical path shape; the adapter resolves it before supplying facts."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        return False
    return (os.path.isabs(value) and os.path.normpath(value) == value
            and Path(value).name == expected_name)


class TailscaleExecutableSystembility:
    """Bind the CLI to the canonical executable observed by the read adapter."""

    name = "TailscaleExecutableBoundary"

    def __init__(self, facts: TailscaleAuthorityFacts | None):
        self.facts = facts

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in _TAILSCALE_ACTIONS - {"tailscale.install", "tailscale.install.stage", "tailscale.install.prepare"}:
            return SystembilityResult(self.name, True, "not applicable to this action")
        executable = request.parameters.get("executable")
        valid = (request.target == "tailscale" and isinstance(self.facts, TailscaleAuthorityFacts)
                 and executable == self.facts.cli_executable
                 and _canonical_executable_identity(executable, "tailscale"))
        if request.action_id == "tailscale.login":
            valid = (valid and set(request.parameters) == {"executable", "operation"}
                     and request.parameters.get("operation") == "login")
        return SystembilityResult(self.name, bool(valid),
                                  "canonical observed Tailscale executable required")


class TailscalePackageSystembility:
    """Restrict installation to one observed Ubuntu/Debian stable apt recipe."""

    name = "TailscalePackageBoundary"

    def __init__(self, facts: TailscaleAuthorityFacts | None):
        self.facts = facts

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in {"tailscale.install.prepare", "tailscale.install.stage", "tailscale.install"}:
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        facts = self.facts
        if (not isinstance(facts, TailscaleAuthorityFacts)
                or not isinstance(facts.package_manager, str)
                or not isinstance(facts.os_id, str)
                or not isinstance(facts.os_codename, str)):
            return SystembilityResult(self.name, False,
                                      "supported OS and exact official stable package recipe required")
        expected_keys = {"executable", "os_id", "os_codename",
                         "repository_key_url", "repository_list_url", "package",
                         "package_service_effect"}
        if request.action_id == "tailscale.install.prepare":
            expected_keys |= {"private_directory", "key_fingerprint", "source_sha256",
                              "config_sha256", "update_argv"}
        else:
            expected_keys |= {"private_directory", "key_fingerprint", "key_sha256",
                              "source_sha256", "config_sha256", "indexes_digest",
                              "package_version", "archive_sha256", "archive_name",
                              "simulation_digest", "package_actions", "stage_directory",
                              "stage_manifest_digest", "install_argv",
                              "privilege_argv"}
            if request.action_id == "tailscale.install.stage":
                expected_keys |= {"stage_artifacts", "stage_operations",
                                  "stage_operations_digest"}
        valid = (request.target == "tailscale"
                 and set(params) == expected_keys
                 and params.get("executable") == facts.package_manager
                 and _canonical_executable_identity(facts.package_manager, "apt-get")
                 and facts.os_id in _SUPPORTED_TAILSCALE_APT
                 and facts.os_codename in _SUPPORTED_TAILSCALE_APT.get(facts.os_id, ())
                 and params.get("os_id") == facts.os_id
                 and params.get("os_codename") == facts.os_codename
                 and params.get("package") == "tailscale"
                 and params.get("package_service_effect") ==
                     "may_start_or_restart_tailscaled")
        if valid:
            base = f"https://pkgs.tailscale.com/stable/{facts.os_id}/{facts.os_codename}"
            valid = (params.get("repository_key_url") == base + ".noarmor.gpg"
                     and params.get("repository_list_url") == base + ".tailscale-keyring.list")
        if valid:
            directory = params.get("private_directory")
            private_parent = state_root().expanduser().absolute() / "tailscale-apt"
            valid = (isinstance(directory, str)
                     and Path(directory).parent == private_parent
                     and re.fullmatch(r"[0-9a-f]{16}-[0-9a-f]{32}", Path(directory).name) is not None
                     and params.get("key_fingerprint") ==
                     "2596A99EAAB33821893C0A79458CA832957F5868")
        if valid and request.action_id in {"tailscale.install.stage", "tailscale.install"}:
            version = params.get("package_version")
            actions = params.get("package_actions")
            argv = params.get("install_argv")
            expected_argv = (facts.package_manager, "install", "--yes", "--no-upgrade",
                             "--no-remove", "--no-download", "--no-install-recommends",
                             f"tailscale={version}")
            valid = (isinstance(version, str)
                     and re.fullmatch(r"[A-Za-z0-9.+:~_-]{1,160}", version) is not None
                     and actions == (f"Inst tailscale={version}", f"Conf tailscale={version}")
                     and argv == expected_argv
                     and params.get("privilege_argv") ==
                     ("/usr/bin/pkexec", "/usr/bin/env",
                      f"APT_CONFIG={params['stage_directory']}/apt.conf",
                      "DEBIAN_FRONTEND=noninteractive", *expected_argv)
                     and params.get("stage_directory") ==
                     f"/var/lib/isycode/tailscale/{Path(params['private_directory']).name}"
                     and all(isinstance(params.get(key), str)
                             and re.fullmatch(r"[0-9a-f]{64}", params[key]) is not None
                             for key in ("key_sha256", "source_sha256", "config_sha256",
                                         "indexes_digest", "archive_sha256", "simulation_digest",
                                         "stage_manifest_digest"))
                     and isinstance(params.get("archive_name"), str)
                     and re.fullmatch(r"tailscale_[A-Za-z0-9.+:~_-]+_[A-Za-z0-9]+\.deb",
                                      params["archive_name"]) is not None)
        if valid and request.action_id == "tailscale.install.prepare":
            valid = (params.get("update_argv") == (facts.package_manager, "update")
                     and all(isinstance(params.get(key), str)
                             and re.fullmatch(r"[0-9a-f]{64}", params[key]) is not None
                             for key in ("source_sha256", "config_sha256")))
        if valid and request.action_id == "tailscale.install.stage":
            raw_artifacts = params.get("stage_artifacts")
            private = Path(params["private_directory"])
            prefix = f"pkgs.tailscale.com_stable_{facts.os_id}_dists_{facts.os_codename}_"
            valid = isinstance(raw_artifacts, tuple) and 5 <= len(raw_artifacts) <= 16
            artifacts = raw_artifacts if isinstance(raw_artifacts, tuple) else ()
            typed_artifacts: list[tuple[str, str, int, str]] = []
            if valid:
                names = []
                total = 0
                for item in artifacts:
                    if (not isinstance(item, tuple) or len(item) != 4
                            or not isinstance(item[0], str) or not isinstance(item[1], str)
                            or type(item[2]) is not int or not isinstance(item[3], str)):
                        valid = False
                        break
                    relative, source, size, digest = item
                    expected_source = {
                        "keyring.gpg": private / "keyring.gpg",
                        "source.list": private / "stage-source.list",
                        "apt.conf": private / "stage-apt.conf",
                    }.get(relative)
                    if relative.startswith("lists/"):
                        name = relative.removeprefix("lists/")
                        if (name.startswith(prefix)
                                and re.fullmatch(r"[A-Za-z0-9_.+%-]{1,240}", name)):
                            expected_source = private / "lists" / name
                    if relative == f"cache/{params['archive_name']}":
                        expected_source = private / "cache" / params["archive_name"]
                    if (expected_source is None or source != str(expected_source)
                            or relative in names or not 0 < size <= 80 * 1024 * 1024
                            or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
                        valid = False
                        break
                    names.append(relative)
                    total += size
                    typed_artifacts.append((relative, source, size, digest))
                valid = (valid and names[:3] == ["keyring.gpg", "source.list", "apt.conf"]
                         and names[-1] == f"cache/{params['archive_name']}"
                         and sum(name.startswith("lists/") for name in names) >= 2
                         and total <= 32 * 1024 * 1024 + 80 * 1024 * 1024 + 4 * 16 * 1024)
            if valid:
                manifest = [(relative, size, digest)
                            for relative, _, size, digest in typed_artifacts]
                expected_digest = hashlib.sha256(json.dumps(
                    (params["stage_directory"], manifest), separators=(",", ":")).encode()).hexdigest()
                operations = tailscale_stage_operations(params["stage_directory"],
                                                        tuple(typed_artifacts))
                operations_digest = hashlib.sha256(json.dumps(
                    operations, separators=(",", ":")).encode()).hexdigest()
                valid = (params["stage_manifest_digest"] == expected_digest
                         and params.get("stage_operations") == operations
                         and params.get("stage_operations_digest") == operations_digest)
        return SystembilityResult(self.name, bool(valid),
                                  "supported OS and exact official stable package recipe required")


class TailscaleGatewaySystembility:
    """Keep the configured Gateway on its exact loopback endpoint and port."""

    name = "TailscaleGatewayBoundary"

    def __init__(self, facts: TailscaleAuthorityFacts | None):
        self.facts = facts

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in _TAILSCALE_SERVE_ACTIONS | {"tailscale.inspect"}:
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        facts = self.facts
        if (not isinstance(facts, TailscaleAuthorityFacts)
                or not isinstance(facts.gateway_url, str)
                or type(facts.gateway_port) is not int):
            return SystembilityResult(self.name, False,
                                      "exact configured loopback Gateway endpoint required")
        valid = (request.target == "tailscale"
                 and _valid_gateway(facts.gateway_url or "", facts.gateway_port)
                 and params.get("gateway_url") == facts.gateway_url
                 and type(params.get("gateway_port")) is int
                 and params.get("gateway_port") == facts.gateway_port)
        if request.action_id == "tailscale.inspect":
            valid = valid and set(params) == {"executable", "gateway_url", "gateway_port"}
        return SystembilityResult(self.name, bool(valid),
                                  "exact configured loopback Gateway endpoint required")


class TailscalePrivateServeSystembility:
    """Bind a proposed private route to a complete live inventory and ownership."""

    name = "TailscalePrivateServeBoundary"

    def __init__(self, facts: TailscaleAuthorityFacts | None):
        self.facts = facts

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in _TAILSCALE_SERVE_ACTIONS:
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        facts = self.facts
        if not isinstance(facts, TailscaleAuthorityFacts):
            return SystembilityResult(self.name, False,
                                      "private Serve route must be free or match live and owned identity")
        route = facts.proposed_route
        if (not isinstance(route, ServeRoute) or not isinstance(facts.cli_executable, str)
                or not isinstance(facts.gateway_url, str)
                or not isinstance(facts.serve_digest, str)
                or facts.live_routes is None or facts.route_id is None):
            return SystembilityResult(self.name, False,
                                      "private Serve route must be free or match live and owned identity")
        valid = (request.target == "tailscale" and set(params) == _TAILSCALE_SERVE_KEYS
                 and route.private is True
                 and facts.serve_inventory_complete is True
                 and type(facts.live_routes) is tuple
                 and all(isinstance(item, ServeRoute) for item in facts.live_routes)
                 and isinstance(facts.route_id, str)
                 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", facts.route_id) is not None
                 and isinstance(route.host, str)
                 and re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts\.net:443", route.host) is not None
                 and route.path == "/isycode" and route.target == facts.gateway_url
                 and isinstance(facts.serve_digest, str)
                 and re.fullmatch(r"[0-9a-f]{64}", facts.serve_digest) is not None
                 and params.get("route_id") == facts.route_id
                 and params.get("route_host") == route.host
                 and params.get("route_path") == route.path
                 and params.get("route_target") == route.target
                 and params.get("serve_digest") == facts.serve_digest
                 and params.get("mode") == "private" and params.get("funnel") is False)
        if valid:
            executable = facts.cli_executable
            expected_argv = (executable, "serve", "--https=443",
                             "--set-path=/isycode", "--bg", facts.gateway_url)
            if request.action_id == "tailscale.serve.disable":
                expected_argv += ("off",)
            valid = (params.get("serve_argv") == expected_argv
                     and params.get("serve_delta_digest") == tailscale_serve_delta_digest(
                         request.action_id, facts.serve_digest, route, expected_argv))
        if valid:
            matching = tuple(item for item in facts.live_routes
                             if (item.host, item.path) == (route.host, route.path))
            owned = facts.owned_route
            owned_matches = (isinstance(owned, OwnedServeRoute)
                             and (owned.route_id, owned.host, owned.path, owned.target)
                             == (facts.route_id, route.host, route.path, route.target))
            if request.action_id == "tailscale.serve.enable":
                valid = ((not matching and owned is None)
                         or (len(matching) == 1 and matching[0] == route and owned_matches))
            else:
                valid = owned_matches and (not matching or
                                           (len(matching) == 1 and matching[0] == route))
        return SystembilityResult(self.name, bool(valid),
                                  "private Serve route must be free or match live and owned identity")


class MobileHostSystembility:
    """Keep mobile pairing bound to the loopback host and its one-use PIN."""

    name = "MobileHostBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        del authority
        if request.action_id not in {"mobile.host.start", "mobile.pair", "mobile.pair.issue"}:
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        if request.action_id == "mobile.host.start":
            valid = (request.target == "127.0.0.1:8765"
                     and params == {"bind": "127.0.0.1", "port": 8765,
                                    "transport": "loopback"})
            return SystembilityResult(self.name, valid,
                                      "Mobile Host is restricted to loopback on port 8765")
        if request.action_id == "mobile.pair":
            challenge_id = params.get("challenge_id")
            valid = (request.target == "mobile-host"
                     and set(params) == {"challenge_id", "device_name"}
                     and isinstance(challenge_id, str)
                     and re.fullmatch(r"[0-9a-f]{64}", challenge_id) is not None
                     and isinstance(params.get("device_name"), str)
                     and 1 <= len(params["device_name"]) <= 96)
            return SystembilityResult(self.name, valid,
                                      "Pairing requires a verified one-use PIN and bounded device label")
        if request.action_id == "mobile.pair.issue":
            replaced = params.get("replaces_challenge")
            valid = (request.target == "mobile-host"
                     and set(params) == {"host", "replaces_challenge"}
                     and params.get("host") == "127.0.0.1:8765"
                     and isinstance(replaced, str)
                     and (replaced == "none"
                          or re.fullmatch(r"[0-9a-f]{64}", replaced) is not None))
            return SystembilityResult(self.name, valid,
                                      "A new PIN is issued only for the loopback host and bound "
                                      "to the challenge it replaces")
        return SystembilityResult(self.name, False, "Mobile Host owner does not implement this action")


class BridgePresenceSystembility:
    """Allow only a reviewed local agents listing. Never connect, send, or wake."""

    name = "BridgePresenceBoundary"

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        del authority
        if request.action_id != "bridge.agents":
            return SystembilityResult(self.name, True, "not applicable to this action")
        params = request.parameters
        handshake = params.get("handshake")
        valid = (
            request.target == "agents"
            and request.execution_owner == "bridge_presence"
            and set(params) == {"executable", "handshake", "sha256", "operation"}
            and params.get("operation") == "agents"
            and isinstance(params.get("executable"), str)
            and params["executable"].startswith("/")
            and isinstance(handshake, str)
            and handshake.endswith("/handshake.py")
            and ".." not in Path(handshake).parts
            and isinstance(params.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", params["sha256"]) is not None
        )
        return SystembilityResult(
            self.name, valid, "presence read is limited to the agents listing")


class ProductActionGate:
    """Run explicit Workspace Authority followed by the pure ISySentinel."""

    def __init__(self, root: Path, authority: WorkspaceAuthority, *, owner_id: str,
                 tailscale_facts: TailscaleAuthorityFacts | None = None,
                 journal: bool = True):
        canonical = root.resolve(strict=True)
        self.owner_id = owner_id if isinstance(owner_id, str) else ""
        owner_id = self.owner_id
        allowed_actions = OWNER_ACTIONS.get(owner_id, frozenset())

        class ExecutionOwnerBindingSystembility:
            name = "ExecutionOwnerBinding"

            def evaluate(self, request: ActionRequest,
                         authority: AuthorityDecision) -> SystembilityResult:
                variants = [item for item in OWNER_ACTION_VARIANTS
                            if item.action_id == request.action_id]
                owner_variants = [item for item in variants if item.owner_id == owner_id]
                denied = request.action_id in EXPLICIT_DENY_ACTIONS
                bound = (not denied and request.workspace_root == canonical
                         and request.execution_owner == owner_id
                         and request.action_id in allowed_actions
                         and (not variants or any(item.matches(request) for item in owner_variants)))
                if denied:
                    reason = "action is explicitly denied in Secure"
                elif not owner_id or not allowed_actions:
                    reason = "no execution owner is registered for this gate"
                elif request.workspace_root != canonical:
                    reason = "request workspace does not match execution owner"
                elif request.execution_owner != owner_id:
                    reason = "request is bound to a different execution owner"
                elif request.action_id not in allowed_actions:
                    reason = "execution owner has no implementation for this action"
                elif variants and not any(item.matches(request) for item in owner_variants):
                    reason = "request does not match this owner's declared action variant"
                else:
                    reason = "action is registered to this concrete execution owner and variant"
                return SystembilityResult(self.name, bound, reason)

        self.authority = authority
        if journal:
            try:
                self.audit: ActionAuditJournal | None = ActionAuditJournal(canonical)
            except ActionAuditError:
                self.audit = None
        else:
            self.audit = None
        self.sentinel = IsySentinel([
            ExecutionOwnerBindingSystembility(),
            WorkspaceReadSystembility(canonical), WorkspaceWriteSystembility(canonical),
            WorkspaceConfigBoundary(canonical),
            ProviderAuthSystembility(), ProviderNetworkSystembility(),
            RemoteReadSystembility(), SessionStoreSystembility(), SessionDeleteSystembility(),
            CredentialBoundarySystembility(),
            MCPInvocationSystembility(),
            GatewaySemanticSystembility(), LSPStartSystembility(), BrokerPreviewSystembility(),
            BrokerProvisionSystembility(), BrokerManagementSystembility(),
            TailscaleExecutableSystembility(tailscale_facts),
            TailscalePackageSystembility(tailscale_facts),
            TailscaleGatewaySystembility(tailscale_facts),
            TailscalePrivateServeSystembility(tailscale_facts),
            MobileHostSystembility(), CommandProcessSystembility(), GitSystembility(),
            PublishSystembility(), LocalMCPSystembility(), ClipboardSystembility(),
            BridgePresenceSystembility(),
        ])

    def preview(self, request: ActionRequest):
        """Evaluate the real grant/Systembility chain without audit or approval consumption."""
        from isycode.effect_policy import POLICY_VERSION, stamp
        try:
            bound = stamp(request)
            classified = (bound.policy_version == POLICY_VERSION
                          and bound.request_digest == request.digest
                          and bound.action_id == request.action_id)
        except (KeyError, TypeError, ValueError):
            classified = False
        if not classified:
            digest = request.digest if isinstance(request, ActionRequest) else ""
            action_id = request.action_id if isinstance(request, ActionRequest) else ""
            reason = "action has no effect classification"
            return (
                AuthorityDecision(False, "", reason, digest),
                SentinelDecision(action_id, digest, (
                    DecisionCheck("EffectClass", False, reason),)),
            )
        authority = self.authority.evaluate(request, preview=True)
        return authority, self.sentinel.evaluate(request, authority)

    def authorize(self, request: ActionRequest, *, approvals: ActionApprovalStore | None = None,
                  approval: ActionApproval | None = None):
        # Classification is fail-closed and stays off the success path: a known
        # action keeps the existing Sentinel checks, and a missing class denies
        # before any effect. The policy version is not written into the journal.
        from isycode.effect_policy import POLICY_VERSION, stamp
        try:
            bound = stamp(request)
            classified = (bound.policy_version == POLICY_VERSION
                          and bound.request_digest == request.digest
                          and bound.action_id == request.action_id)
        except (KeyError, TypeError, ValueError):
            classified = False
        if not classified:
            digest = request.digest if isinstance(request, ActionRequest) else ""
            action_id = request.action_id if isinstance(request, ActionRequest) else ""
            reason = "action has no effect classification"
            return (
                AuthorityDecision(False, "", reason, digest),
                SentinelDecision(action_id, digest, (
                    DecisionCheck("EffectClass", False, reason),)),
            )
        authority = self.authority.evaluate(request, approvals=approvals, approval=approval)
        decision = self.sentinel.evaluate(request, authority)
        try:
            if self.audit is None:
                raise ActionAuditError("journal is unavailable")
            self.audit.record_decision(
                request, authority, decision,
                approval_mode=getattr(approval, "mode", None) if approval is not None else None)
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
               approval: ActionApproval | None, *, expected_revision: object = None) -> ActionOutcome:
        """Delete one transcript; with ``expected_revision`` (the revision the user
        reviewed) it refuses if another instance changed it since then."""
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
        from isycode.chat_sessions import SessionDiverged
        try:
            if expected_revision is None:  # other stores (iteration ledgers) have no revisions
                self.store.delete(session_id)
            else:
                self.store.delete(session_id, expected_revision=expected_revision)
        except SessionDiverged:
            return ActionOutcome("Session not deleted.", "DENY", None,
                                 "session_divergence_detected: the conversation changed in another "
                                 "ISyCode window or process after you reviewed it")
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
            expected_identity = gateway_workspace_id(self.root)
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
                    "server_executable", "node_executable", "sandbox_executable", "runtime_executable"))):
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
                 "node_executable": server["node_executable"],
                 **({"runtime_executable": server["runtime_executable"]} if server.get("runtime_executable") else {})},
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

    async def diagnostics(self, server_id: str, path: str, text: str,
                                      catalog: list[dict[str, Any]]) -> ActionOutcome:
        """Check one Python file after an edit; read-only, so no per-run approval."""
        from isycode.lsp import discover_servers, pyright_diagnostics

        server = next((item for item in catalog if item.get("id") == server_id), None)
        current = next((item for item in discover_servers() if item.get("id") == server_id), None)
        if (server is None or current is None or server.get("state") != "sandbox_ready"
                or any(server.get(key) != current.get(key) for key in (
                    "server_executable", "node_executable", "sandbox_executable", "runtime_executable"))):
            return ActionOutcome("LSP diagnostics denied.", "DENY", None,
                                 "adapter catalog changed or is not sandbox-ready")
        if not isinstance(path, str) or not isinstance(text, str):
            return ActionOutcome("LSP diagnostics denied.", "DENY", None, "invalid diagnostics request")
        # The server reads the whole root; the file itself must be readable too.
        for target in (str(self.root), str(self.root / path)):
            read_request = ActionRequest("workspace.files.read", self.root, target, {"path": target},
                                         execution_owner="lsp_symbols")
            _, read_decision = self.gate.authorize(read_request)
            if not read_decision.allowed:
                reason = "; ".join(check.reason for check in read_decision.checks if not check.passed)
                return ActionOutcome("LSP diagnostics denied.", "DENY", None,
                                     "workspace.files.read grant required: " + reason)
        try:
            request = ActionRequest(
                "lsp.diagnostics", self.root, server_id,
                {"operation": "textDocument/publishDiagnostics", "server_id": server_id,
                 "path": path, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                 "workspace_root": str(self.root), "executable": server["sandbox_executable"],
                 "server_executable": server["server_executable"],
                 "node_executable": server["node_executable"]},
                execution_owner="lsp_symbols")
        except (TypeError, ValueError):
            return ActionOutcome("LSP diagnostics denied.", "DENY", None, "invalid diagnostics request")
        _, decision = self.gate.authorize(request)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome("LSP diagnostics denied.", "DENY", None, reason)
        try:
            result = await pyright_diagnostics(self.root, path, text, server)
            result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError) as exc:
            return ActionOutcome("LSP diagnostics failed.", "ERROR", None,
                                 f"sandboxed diagnostics failed ({type(exc).__name__})")
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "lsp.diagnostics", request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result_text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result_text) or not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("LSP receipt could not be persisted.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(result_text, "ALLOW", receipt, "diagnostics received from the sandboxed server")


class ProviderNetworkOwner:
    """Authorize one provider request and durably receipt its response.

    The transport callback is supplied by trusted ISyCode code, never by a
    model or workspace file. Its request material is hashed into the immutable
    action identity; neither prompt nor response contents enter the journal.
    """

    def __init__(self, root: Path, authority: WorkspaceAuthority):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.gate = ProductActionGate(self.root, authority, owner_id="provider_network")

    async def execute(self, provider: Any, request_material: Any,
                      send: Callable[[], Awaitable[Any]]) -> tuple[Any | None, ActionOutcome]:
        try:
            url = provider.base_url
            parsed = urlsplit(url)
            host = (parsed.hostname or "").casefold().rstrip(".")
            if parsed.port:
                host += f":{parsed.port}"
            connector = getattr(provider, "connector_identity", None)
            if provider.name == "chatgpt":
                if not isinstance(request_material, dict) or not ProviderAuthSystembility.identity_valid(connector):
                    raise ValueError("invalid subscription connector identity")
                request_material = {**request_material, "connector": connector}
            material = json.dumps(request_material, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"))
            material_digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
            request = ActionRequest(
                "provider.request", self.root, host,
                {"provider": provider.name, "model": provider.model,
                 "url": url, "payload_digest": material_digest,
                 **({"connector": connector} if provider.name == "chatgpt" else {})},
                execution_owner="provider_network")
        except (AttributeError, TypeError, ValueError, OSError):
            return None, ActionOutcome("Provider request denied.", "DENY", None,
                                       "provider request identity is invalid")

        authority, decision = self.gate.authorize(request)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return None, ActionOutcome("Provider request denied.", "DENY", None,
                                       reason or authority.reason)
        from isycode import egress
        try:
            egress.review_destination(url)
        except egress.EgressDenied as exc:
            return None, ActionOutcome("Provider request denied.", "DENY", None, str(exc))
        response = await send()
        try:
            result_text = json.dumps(response, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"))
        except (TypeError, ValueError):
            return None, ActionOutcome("Provider response is not verifiable.", "NOT_VERIFIABLE", None,
                                       "provider result is not JSON serializable")
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "provider.request", request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result_text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result_text) or not self.gate.persist_receipt(request, receipt):
            return None, ActionOutcome("Provider response is not verifiable.", "NOT_VERIFIABLE", None,
                                       "durable provider receipt could not be verified or persisted")
        return response, ActionOutcome(result_text, "ALLOW", receipt,
                                       "provider response is bound to the authorized request digest")


class LocalWorkspaceReadOwner:
    """Execute only list/read/name-search after grant and Sentinel ALLOW."""

    def __init__(self, root: Path, authority: WorkspaceAuthority, *,
                 owner_id: str = "workspace_read"):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.owner_id = owner_id
        self.gate = ProductActionGate(self.root, authority, owner_id=owner_id)

    def execute(self, action_id: str, arguments: dict[str, Any]) -> ActionOutcome:
        allowed = READ_ACTIONS if self.owner_id == "workspace_read" else (
            CONFIG_READ_ACTIONS if self.owner_id == CONFIG_OWNER_ID else frozenset())
        if action_id not in allowed:
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
        if self.owner_id == CONFIG_OWNER_ID:
            request = _workspace_config_request(action_id, self.root, target, arguments)
        else:
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
            if action_id in {"workspace.files.list", "workspace.config.list"}:
                result = self._list(target)
            elif action_id == "workspace.files.read" and "query" in arguments:
                query = arguments.get("query", "")
                if not isinstance(query, str) or not query.strip() or len(query) > 256:
                    raise ValueError("search text must contain 1–256 characters")
                result = self._grep(query, Path(target))
            elif action_id in {"workspace.files.read", "workspace.context.inject",
                               "workspace.config.read"}:
                if action_id == "workspace.config.read":
                    relative = Path(target).relative_to(self.root).as_posix()
                    limit = (CONFIG_JSON_MAX_BYTES if relative == ".isycode/config.json"
                             else CONFIG_COMMAND_MAX_BYTES if relative.startswith(".isycode/commands/")
                             else CONFIG_MAX_BYTES)
                    result = self._read(target, max_bytes=limit)
                else:
                    result = self._read(target)
            else:
                query = arguments.get("query", "")
                if not isinstance(query, str) or not query.strip() or len(query) > 256:
                    raise ValueError("search query must contain 1–256 characters")
                result = self._search(query.strip(), Path(target))
        except (OSError, ValueError) as exc:
            return ActionOutcome("Read action failed; no content was returned.",
                                 "ERROR", None, str(exc)[:300])
        if len(result) > MAX_OUTPUT_CHARS and not (
                self.owner_id == CONFIG_OWNER_ID and action_id == "workspace.config.read"
                and Path(target).relative_to(self.root).as_posix() == ".gitignore"):
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

    def _entries(self, directory: Path) -> list[Any]:
        """Directory entries without following links (descriptor walk, or verified paths)."""
        if use_verified_fs():
            return VerifiedFS(self.root).list_dir(directory)
        descriptor = self._open_directory(directory)
        try:
            with os.scandir(descriptor) as iterator:
                return list(iterator)
        finally:
            os.close(descriptor)

    def _list(self, target: str) -> str:
        directory = Path(target)
        entries = []
        for item in self._entries(directory):
            if WorkspaceReadSystembility.is_sensitive_name(item.name) or item.is_symlink():
                continue
            kind = "directory" if item.is_dir(follow_symlinks=False) else "file"
            entries.append({"name": item.name, "kind": kind})
            if len(entries) >= 1000:
                break
        entries.sort(key=lambda value: (value["kind"] != "directory", value["name"].casefold()))
        return json.dumps({"path": str(directory.relative_to(self.root) or "."),
                           "entries": entries}, ensure_ascii=False)

    def _read(self, target: str, *, max_bytes: int = MAX_FILE_BYTES) -> str:
        path = Path(target)
        descriptor = self._open_file(path)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("selected path is not a regular file")
            if info.st_size > max_bytes:
                raise ValueError(f"file exceeds the {max_bytes // 1024} KiB read limit")
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"file grew past the {max_bytes // 1024} KiB read limit")
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
            try:
                listed = self._entries(directory)
            except OSError:
                continue
            children = []
            for child in listed:
                children.append(child)
                entries_seen += 1
                if entries_seen >= MAX_SCAN_ENTRIES:
                    truncated = True
                    break
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

    def _grep(self, query: str, start: Path) -> str:
        """Literal, case-insensitive line search through descriptor-safe reads."""
        folded = query.casefold()
        matches: list[dict[str, Any]] = []
        files = scanned_bytes = 0
        truncated = False
        pending = [start]
        if start != self.root and not start.is_dir():
            pending, candidates = [], [start]
        else:
            candidates = []
        while pending or candidates:
            if candidates:
                path = candidates.pop()
                if files >= GREP_MAX_FILES or scanned_bytes >= GREP_MAX_BYTES:
                    truncated = True
                    break
                try:
                    descriptor = self._open_file(path)
                except OSError:
                    continue
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                        continue
                    data = stream.read(MAX_FILE_BYTES + 1)
                files += 1
                scanned_bytes += len(data)
                if len(data) > MAX_FILE_BYTES or b"\0" in data[:8192]:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if folded in line.casefold():
                        matches.append({"path": str(path.relative_to(self.root)),
                                        "line": number, "text": line.strip()[:300]})
                        if len(matches) >= GREP_MAX_MATCHES:
                            truncated = True
                            break
                if truncated:
                    break
                continue
            directory = pending.pop()
            try:
                children = sorted(self._entries(directory), key=lambda item: item.name)
            except OSError:
                continue
            for child in reversed(children):
                if (WorkspaceReadSystembility.is_sensitive_name(child.name) or child.is_symlink()
                        or child.name in GREP_SKIP_DIRECTORIES):
                    continue
                if child.is_dir(follow_symlinks=False):
                    pending.append(directory / child.name)
                elif child.is_file(follow_symlinks=False):
                    candidates.append(directory / child.name)
        return json.dumps({"query": query, "matches": matches, "files_scanned": files,
                           "truncated": truncated}, ensure_ascii=False)

    def _open_directory(self, directory: Path) -> int:
        if use_verified_fs():
            raise OSError("descriptor walks are not available on this platform")
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
        if use_verified_fs():
            return VerifiedFS(self.root).open_read(path)
        parent_fd = self._open_directory(path.parent)
        try:
            # Open before checking the descriptor's type without waiting for a
            # FIFO writer. A repository-controlled named pipe must not pin an
            # executor thread (or prevent shutdown after cancellation).
            return os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                           | getattr(os, "O_NONBLOCK", 0),
                           dir_fd=parent_fd)
        finally:
            os.close(parent_fd)


__all__ = ["ActionOutcome", "ActionReceipt", "CHAT_WORKSPACE_TOOLS",
           "LocalWorkspaceReadOwner", "ProductActionGate", "ProviderNetworkSystembility",
           "RemoteReadSystembility", "SessionDeleteOwner", "SessionDeleteSystembility",
           "READ_ACTIONS", "TOOL_ACTIONS"]
