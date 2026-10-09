"""Reproducible, explicit inventory of action owners and known effect callsites.

This is a contract report, not a source-code oracle: callsites are named
deliberately and reviewed alongside the owners. A missing declaration is a
coverage gap, never an implicit grant or owner.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from isycode.actions import ACTION_BY_ID, ACTION_CATALOG
from isycode.action_runtime import (
    EXPLICIT_DENY_ACTIONS, OWNER_ACTIONS, OWNER_ACTION_VARIANTS,
    OWNER_REQUIRED_SYSTEMBILITIES,
)


# These multiple bindings are deliberate child reads within an independently
# bound operation. They are distinct from action variants, which must carry an
# explicit request discriminator and owner-specific runtime check.
ALLOWED_SHARED_ACTION_OWNERS = {
    "workspace.files.read": frozenset({
        "workspace_read", "lsp_symbols", "broker_preview", "broker_provision",
        "grit_peers",
    }),
}

# Local conversational role selection does not request a product permission.
NON_AUTHORITY_ACTIONS = frozenset({"role.select"})

# The small set of source constructors whose action identifier is a variable.
# Their selector implementations are exercised by focused tests; a new dynamic
# constructor has no contract here and blocks the frontier report.
DYNAMIC_ACTION_RESOLVERS = {
    "isycode.action_runtime.LocalWorkspaceReadOwner.execute": {
        "owner": "workspace_read",
        "actions": ("workspace.files.list", "workspace.files.read",
                    "workspace.files.search", "workspace.context.inject"),
    },
    "isycode.action_runtime._workspace_config_request": {
        "owner": "workspace_config",
        "actions": ("workspace.config.read", "workspace.config.list"),
    },
    "isycode.git_owner.GitOwner._request": {
        "owner": "workspace_git",
        "actions": ("git.status", "git.diff", "git.commit"),
    },
    "isycode.broker.BrokerManagementOwner.request_for": {
        "owner": "broker_management",
        "actions": ("broker.health", "broker.logs", "broker.start",
                    "broker.stop", "broker.remove"),
    },
    "isycode.tui_app_workspace.WorkspaceMixin._workspace_request": {
        "owner": "workspace_read",
        "actions": ("workspace.files.list", "workspace.files.read",
                    "workspace.files.search", "workspace.context.inject"),
    },
    "isycode.tui_app_remote.RemoteMixin._authorize_remote_read": {
        "owner": "remote_catalog",
        "actions": ("catalog.external.read", "gateway.files.read", "mcp.discover"),
    },
    "isycode.workspace_memory.WorkspaceMemoryOwner.prepare": {
        "owner": "workspace_memory",
        "actions": ("workspace.memory.read", "workspace.memory.write",
                    "workspace.memory.forget"),
    },
    "isycode.tailscale_serve.TailscaleServeOwner._prepare": {
        "owner": "tailscale_serve",
        "actions": ("tailscale.serve.enable", "tailscale.serve.disable"),
    },
    "isycode.tailscale_read.TailscaleReadOwner.inspect": {
        "owner": "tailscale_read",
        "actions": ("tailscale.inspect",),
    },
}

_SECURE_DIRECT_API_METHODS = {
    "MobileHost": frozenset({"start", "stop", "_pair", "rotate_pairing_code"}),
    "ApiKeyStore": frozenset({"issue", "revoke"}),
    "BridgeClient": frozenset({
        "hello", "heartbeat", "peek", "goodbye", "status", "agents",
        "claim", "release", "send", "_run",
    }),
    "ChatSessionStore": frozenset({
        "create", "append", "load", "list_sessions", "rename", "fork", "delete", "save",
        "import_json",
    }),
    "MemoryStore": frozenset({"perform"}),
}
_SECURE_DIRECT_FUNCTIONS = frozenset({
    "choose_context_file", "choose_workspace_file", "choose_workspace_directory",
})

# Low-level effect primitives and the only product functions allowed to call
# them ("module.Class.function"). Any other call in src/isycode (including
# constructing BridgeClient) is reported and keeps secure_closed false.
PRIMITIVE_CALLERS: dict[tuple[str, str], frozenset[str]] = {
    ("ApiKeyStore", "issue"): frozenset({"mobile_host.MobileHost._pair"}),
    ("ApiKeyStore", "revoke"): frozenset({"mobile_host.MobileHost._pair"}),
    ("ChatSessionStore", "rename"): frozenset(),
    ("ChatSessionStore", "fork"): frozenset(),
    ("ChatSessionStore", "create"): frozenset(),
    ("BridgeClient", "__init__"): frozenset(),
    ("MemoryStore", "perform"): frozenset({"workspace_memory.WorkspaceMemoryOwner.execute"}),
}
# Modules that define a primitive; their own internal calls are not callers.
_PRIMITIVE_HOME = {"ApiKeyStore": "mobile_host", "ChatSessionStore": "chat_sessions",
                   "BridgeClient": "bridge", "MemoryStore": "workspace_memory"}


def _guarded_bindings(trees: dict[str, ast.AST]) -> dict[str, set[str]]:
    """Names and attributes that hold a guarded primitive, across the package.

    A binding is anything assigned from ``Class(...)``, annotated as ``Class``
    (parameters, attributes, return types of properties/functions), so
    ``self.store.rename`` is recognised even when the name says nothing.
    """
    classes = set(_PRIMITIVE_HOME)
    bound: dict[str, set[str]] = {name: set() for name in classes}

    def class_of(node: ast.AST | None) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Call):
            node = node.func
        if isinstance(node, ast.Subscript):  # Optional[...] / X | None handled below
            return class_of(node.slice)
        if isinstance(node, ast.BinOp):
            return class_of(node.left) or class_of(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.replace("|", " ").replace("None", " ").split()
            return next((part for part in text if part in classes), None)
        name = _ast_name(node).rsplit(".", 1)[-1]
        return name if name in classes else None

    def target_name(node: ast.AST) -> str:
        return _ast_name(node).rsplit(".", 1)[-1]

    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                kind = class_of(node.value)
                if kind:
                    for target in node.targets:
                        if target_name(target):
                            bound[kind].add(target_name(target))
            elif isinstance(node, ast.AnnAssign):
                kind = class_of(node.annotation) or (
                    class_of(node.value) if isinstance(node.value, ast.Call) else None)
                if kind and target_name(node.target):
                    bound[kind].add(target_name(node.target))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = class_of(node.returns)
                if kind:
                    bound[kind].add(node.name)
                for arg in [*node.args.args, *node.args.kwonlyargs]:
                    kind = class_of(arg.annotation)
                    if kind:
                        bound[kind].add(arg.arg)
    return bound


def primitive_caller_violations(package: Path | None = None) -> list[dict[str, Any]]:
    """Calls to guarded primitives from anywhere but their allowed owners."""
    package = package or Path(__file__).resolve().parent
    trees: dict[str, ast.AST] = {}
    violations: list[dict[str, Any]] = []
    for path in sorted(package.rglob("*.py")):
        module = path.relative_to(package).with_suffix("").as_posix().replace("/", ".")
        if module == "action_coverage":
            continue
        try:
            trees[module] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            violations.append({"callsite": module, "reason": f"source unavailable ({type(exc).__name__})"})
    bound = _guarded_bindings(trees)

    def holds(receiver: str, class_name: str) -> bool:
        last = receiver.rsplit(".", 1)[-1]
        return last in bound[class_name] or _receiver_matches_api(receiver, class_name)

    for module, tree in trees.items():
        def visit(node: ast.AST, scope: list[str]) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit(child, scope + [child.name])
                    continue
                if isinstance(child, ast.Call):
                    check(child, scope)
                visit(child, scope)

        def check(call: ast.Call, scope: list[str]) -> None:
            where = ".".join([module, *scope])
            func = call.func
            if isinstance(func, ast.Name) and func.id == "BridgeClient":
                key = ("BridgeClient", "__init__")
                if module == _PRIMITIVE_HOME["BridgeClient"]:
                    return
            elif isinstance(func, ast.Attribute):
                receiver = _ast_name(func.value)
                key = next(((class_name, method) for class_name, method in PRIMITIVE_CALLERS
                            if method == func.attr and holds(receiver, class_name)), None)
                if key is None or (module == _PRIMITIVE_HOME[key[0]] and receiver == "self"):
                    return
            else:
                return
            if where not in PRIMITIVE_CALLERS[key]:
                violations.append({"callsite": f"{where}:{call.lineno}",
                                   "reason": f"{key[0]}.{key[1]} called outside its owner"})

        visit(tree, [])
    return sorted(violations, key=lambda item: item["callsite"])


# Audited effect-producing callsites. Status is explicit because there is no
# reliable automatic way to infer whether an arbitrary Python function is a
# product execution owner.
KNOWN_EFFECT_CALLSITES = (
    ("web.fetch", "WebFetchOwner.execute", "web_fetch", "COVERED"),
    ("session.create", "IterationOwner._persist", "chat_sessions", "COVERED"),
    ("session.resume", "IterationOwner.inspect", "chat_sessions", "COVERED"),
    ("provider.request", "run_iteration.complete", "provider_network", "COVERED"),
    ("tailscale.inspect", "TailscaleReadOwner.inspect", "tailscale_read", "COVERED"),
    ("tailscale.install.prepare", "TailscalePackageInstallOwner.prepare", "tailscale_package_install", "COVERED"),
    ("tailscale.install.stage", "TailscalePackageInstallOwner.stage", "tailscale_package_install", "COVERED"),
    ("tailscale.install", "TailscalePackageInstallOwner.install", "tailscale_package_install", "COVERED"),
    ("tailscale.login", "TailscaleLoginOwner.begin_login", "tailscale_login", "COVERED"),
    ("tailscale.serve.enable", "TailscaleServeOwner.enable", "tailscale_serve", "COVERED"),
    ("tailscale.serve.disable", "TailscaleServeOwner.disable", "tailscale_serve", "COVERED"),
    ("provider.request", "ProviderNetworkOwner.execute", "provider_network", "COVERED"),
    ("provider.authenticate", "ProviderAuthOwner.begin", "provider_auth", "COVERED"),
    ("workspace.files.read", "LocalWorkspaceReadOwner.execute", "workspace_read", "COVERED"),
    ("workspace.config.read", "WorkspaceConfigOwner.read_config", "workspace_config", "COVERED"),
    ("workspace.config.list", "WorkspaceConfigOwner.commands", "workspace_config", "COVERED"),
    ("workspace.config.write", "WorkspaceConfigOwner.apply", "workspace_config", "COVERED"),
    ("workspace.context.inject", "WorkspaceMixin._inject_agent_context", "workspace_read", "COVERED"),
    ("workspace.files.read", "WorkspaceMixin._workspace_request", "workspace_read", "COVERED"),
    ("workspace.files.write", "WorkspaceWriteOwner.apply", "workspace_write", "COVERED"),
    ("workspace.files.restore", "WorkspaceWriteOwner._apply_undo", "workspace_write", "COVERED"),
    ("workspace.files.delete", "WorkspaceWriteOwner._apply_delete", "workspace_write", "COVERED"),
    ("workspace.files.move", "WorkspaceWriteOwner._apply_move", "workspace_write", "COVERED"),
    ("mcp.invoke", "GatewayMCPInvocationOwner.invoke", "gateway_mcp", "COVERED"),
    ("gateway.semantic.read", "GatewaySemanticOwner.invoke", "gateway_semantic", "COVERED"),
    ("lsp.start", "LPSSymbolOwner.search", "lsp_symbols", "COVERED"),
    ("lsp.diagnostics", "LPSSymbolOwner.diagnostics", "lsp_symbols", "COVERED"),
    ("grit.claims.read", "GritPeersOwner.claims", "grit_peers", "COVERED"),
    ("workspace.command.run", "CommandRunOwner.run", "workspace_command", "COVERED"),
    ("git.status", "GitOwner.status", "workspace_git", "COVERED"),
    ("git.status", "GitOwner.is_path_tracked", "workspace_git", "COVERED"),
    ("git.diff", "GitOwner.diff", "workspace_git", "COVERED"),
    ("git.commit", "GitOwner.commit", "workspace_git", "COVERED"),
    ("git.push", "PublishOwner.run", "workspace_publish", "COVERED"),
    ("mcp.local.start", "LocalMCPOwner.start", "mcp_local", "COVERED"),
    ("mcp.local.invoke", "LocalMCPOwner.call", "mcp_local", "COVERED"),
    ("broker.build", "BrokerProvisionOwner.provision", "broker_provision", "COVERED"),
    ("broker.start", "BrokerProvisionOwner.provision", "broker_provision", "COVERED_VARIANT"),
    ("broker.start", "BrokerManagementOwner.perform", "broker_management", "COVERED_VARIANT"),
    ("session.delete", "SessionDeleteOwner.delete", "session_delete", "COVERED"),
    ("workspace.memory.read", "WorkspaceMemoryOwner.execute", "workspace_memory", "COVERED"),
    ("workspace.memory.write", "WorkspaceMemoryOwner.execute", "workspace_memory", "COVERED"),
    ("workspace.memory.forget", "WorkspaceMemoryOwner.execute", "workspace_memory", "COVERED"),
    ("mobile.host.start", "MobileHostOwner.authorize_and_launch", "mobile_host", "COVERED"),
    # TUI shutdown is lifecycle cleanup, not a user-authorized stop action.
    # The catalog action remains explicitly denied in Secure.
    ("mobile.host.stop", "MobileHostOwner.shutdown", "", "BLOCKED_BY_DESIGN"),
    ("mobile.pair", "MobileHostOwner.authorize_pair", "mobile_host", "COVERED"),
    ("mobile.pair.issue", "MobileHostOwner.issue_pairing_pin", "mobile_host", "COVERED"),
    # The pairing credential is minted only inside MobileHost._pair, after the
    # mobile_host owner authorized mobile.pair (Authority + IsySentinel); revoke
    # is that handler's rollback when the pairing receipt cannot be recorded.
    # PRIMITIVE_CALLERS below fails secure_closed if any other caller appears.
    ("mobile.pair", "ApiKeyStore.issue", "mobile_host", "COVERED"),
    ("mobile.pair", "ApiKeyStore.revoke", "mobile_host", "COVERED"),
    # No product module constructs BridgeClient (the Bridge is optional, opt-in
    # coordination used by integration tests and external agents only).
    ("bridge.connect", "BridgeClient.hello", "", "BLOCKED_BY_DESIGN"),
    ("bridge.connect", "BridgeClient.heartbeat", "", "BLOCKED_BY_DESIGN"),
    ("bridge.connect", "BridgeClient.goodbye", "", "BLOCKED_BY_DESIGN"),
    ("bridge.connect", "BridgeClient.status", "", "BLOCKED_BY_DESIGN"),
    ("bridge.connect", "BridgeClient.agents", "", "BLOCKED_BY_DESIGN"),
    ("bridge.connect", "BridgeClient._run", "", "BLOCKED_BY_DESIGN"),
    ("bridge.peek", "BridgeClient.peek", "", "BLOCKED_BY_DESIGN"),
    ("bridge.lease.claim", "BridgeClient.claim", "", "BLOCKED_BY_DESIGN"),
    ("bridge.lease.release", "BridgeClient.release", "", "BLOCKED_BY_DESIGN"),
    ("bridge.send", "BridgeClient.send", "", "BLOCKED_BY_DESIGN"),
    ("credentials.add", "CredentialOwner.add", "credentials", "COVERED"),
    ("credentials.revoke", "CredentialOwner.revoke", "credentials", "COVERED"),
    ("credentials.use", "CredentialUseOwner.secret_for", "credential_use", "COVERED"),
    ("session.create", "ChatSessionOwner.record", "chat_sessions", "COVERED"),
    ("session.resume", "ChatSessionOwner.list_conversations", "chat_sessions", "COVERED"),
    ("session.resume", "ChatSessionOwner.resume", "chat_sessions", "COVERED"),
    # Store primitives with no product caller outside the store: ChatSessionOwner
    # writes through its guarded compare-and-write path instead (rename included).
    ("session.create", "ChatSessionStore.create", "", "BLOCKED_BY_DESIGN"),
    ("session.create", "ChatSessionStore.rename", "", "BLOCKED_BY_DESIGN"),
    ("session.create", "ChatSessionStore.fork", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "RemoteMixin._open_broker_preview", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "RemoteMixin._provision_broker", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "tui_app_menu._readme_cmd", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "file_picker.choose_workspace_file", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "file_picker.choose_workspace_directory", "", "BLOCKED_BY_DESIGN"),
    ("clipboard.paste", "ClipboardOwner.paste", "clipboard", "COVERED"),
    ("clipboard.copy", "ClipboardOwner.copy", "clipboard", "COVERED"),
    ("bridge.agents", "BridgePresenceOwner.read", "bridge_presence", "COVERED"),
)


def owner_coverage_report() -> dict[str, Any]:
    """Return the current catalog/owner/callsite coverage without side effects."""
    owners_by_action: dict[str, list[str]] = defaultdict(list)
    unknown_actions: list[str] = []
    for owner, actions in OWNER_ACTIONS.items():
        for action in actions:
            if action not in {item.id for item in ACTION_CATALOG}:
                unknown_actions.append(f"{owner}:{action}")
            owners_by_action[action].append(owner)
    catalog_ids = {item.id for item in ACTION_CATALOG}
    mismatches = sorted(
        f"{owner}:{action}" for owner, actions in OWNER_ACTIONS.items()
        for action in actions if action not in catalog_ids
    )
    variants_by_action: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for variant in OWNER_ACTION_VARIANTS:
        variants_by_action[variant.action_id].append({
            "owner": variant.owner_id,
            "requires": dict(variant.required_parameters),
            "absent": list(variant.absent_parameters),
        })
    conflicts = []
    owner_contract_gaps = []
    variant_contract_gaps = []
    for action, owners in sorted(owners_by_action.items()):
        actual = frozenset(owners)
        permitted = ALLOWED_SHARED_ACTION_OWNERS.get(action)
        if len(actual) > 1 and actual != permitted:
            variants = variants_by_action.get(action, [])
            variant_owners = frozenset(item["owner"] for item in variants)
            if variant_owners != actual or not _variants_are_disjoint(action):
                conflicts.append({"action": action, "owners": sorted(actual)})
    for action, variants in variants_by_action.items():
        declared_owners = frozenset(item["owner"] for item in variants)
        registered_owners = frozenset(owners_by_action.get(action, ()))
        if (action not in catalog_ids or declared_owners != registered_owners
                or not _variants_are_disjoint(action)):
            variant_contract_gaps.append({"action": action,
                                          "variant_owners": sorted(declared_owners),
                                          "registered_owners": sorted(registered_owners)})
    rows = []
    for spec in ACTION_CATALOG:
        owners = sorted(owners_by_action.get(spec.id, []))
        if spec.id in EXPLICIT_DENY_ACTIONS:
            status = "EXPLICIT_DENY" if not owners else "CLASSIFICATION_CONFLICT"
        elif spec.id in NON_AUTHORITY_ACTIONS and not owners:
            status = "SECURE_EXCLUDED"
        elif not owners:
            status = "UNCLASSIFIED"
        elif len(owners) == 1:
            status = "OWNER_VALID"
        elif ALLOWED_SHARED_ACTION_OWNERS.get(spec.id) == frozenset(owners):
            status = "OWNER_SHARED_READ"
        elif variants_by_action.get(spec.id) and _variants_are_disjoint(spec.id):
            status = "OWNER_VARIANTS"
        else:
            status = "AMBIGUOUS"
        for owner in owners:
            if owner not in OWNER_REQUIRED_SYSTEMBILITIES:
                owner_contract_gaps.append({"action": spec.id, "owner": owner,
                                            "reason": "owner has no declared required Systembilities"})
        rows.append({"action": spec.id, "effect": spec.effect,
                     "approval_required": spec.approval_required,
                     "owners": owners,
                     "classification": status,
                     "authority": ("not an effect authority action" if status == "SECURE_EXCLUDED"
                                   else "Workspace Authority" if owners
                                   else "explicit deny at owner binding"),
                     "sentinel": sorted({check for owner in owners
                                          for check in OWNER_REQUIRED_SYSTEMBILITIES.get(owner, ())}),
                     "variants": variants_by_action.get(spec.id, []),
                     "status": status})
    effectful = [row for row in rows if row["effect"] != "read"]
    unowned_effectful = [row["action"] for row in effectful if not row["owners"]]
    callsites = [{"action": action, "callsite": callsite,
                  "owner": owner or None, "status": status}
                 for action, callsite, owner, status in KNOWN_EFFECT_CALLSITES]
    direct_api_bypasses = secure_tui_direct_api_bypasses()
    primitive_violations = primitive_caller_violations()
    stale_callsites = sorted(item["callsite"] for item in callsites
                             if item["status"] != "PLANNED"
                             and not _callsite_exists(item["callsite"]))
    request_constructors = discover_action_request_constructors()
    dynamic_constructors = [item for item in request_constructors
                            if item["action"] is None or item["owner"] is None]
    unresolved_dynamic = []
    for item in dynamic_constructors:
        contract = DYNAMIC_ACTION_RESOLVERS.get(item.get("callable", ""))
        if (contract is None or contract["owner"] != item.get("owner")
                or not set(contract["actions"]) <= set(OWNER_ACTIONS.get(contract["owner"], ()))
                or not set(contract["actions"]) <= catalog_ids):
            unresolved_dynamic.append(item)
    callsites_by_action: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in callsites:
        callsites_by_action[item["action"]].append(item)
    for row in rows:
        if row["classification"] == "EXPLICIT_DENY":
            reachability = "SECURE_EXCLUDED_BY_OWNER_BINDING"
        elif row["classification"] == "SECURE_EXCLUDED":
            reachability = "NOT_AN_EFFECT_ACTION"
        else:
            statuses = {item["status"] for item in callsites_by_action[row["action"]]}
            if statuses and statuses <= {"BLOCKED_BY_DESIGN"}:
                reachability = ("TUI_PATH_BLOCKED; STATIC_ENTRYPOINT_AUDIT_PASS"
                                if not direct_api_bypasses
                                else "TUI_PATH_BLOCKED; STATIC_ENTRYPOINT_AUDIT_FAIL")
            elif statuses & {"COVERED", "COVERED_VARIANT"}:
                reachability = "OWNER_PATH_DECLARED; END_TO_END_REACHABILITY_NOT_PROVEN"
            else:
                reachability = "NOT_DEMONSTRATED"
        row["secure_reachability"] = reachability
    return {
        "actions": rows,
        "callsite_count": len(callsites),
        "callsites": list(callsites),
        "stale_callsites": stale_callsites,
        "request_constructors": request_constructors,
        "dynamic_request_constructors": [item for item in request_constructors
                                          if item["action"] is None or item["owner"] is None],
        "unresolved_dynamic_request_constructors": unresolved_dynamic,
        "owner_action_mismatches": sorted(set(mismatches + unknown_actions)),
        "ambiguous_actions": conflicts,
        "unowned_effectful_actions": unowned_effectful,
        "effectful_callsites_without_mediation": [
            item for item in callsites if item["status"] in {"UNWIRED", "BYPASS_RISK",
                                                         "NOT_DEMONSTRATED", "PLANNED"}
        ],
        "secure_tui_direct_api_bypasses": direct_api_bypasses,
        "secure_tui_closed": (
            not direct_api_bypasses and not conflicts and not mismatches
            and not unclassified_effectful_actions(rows) and not unresolved_dynamic
        ),
        "explicit_denied_actions": sorted(EXPLICIT_DENY_ACTIONS),
        "unclassified_actions": [row["action"] for row in rows
                                 if row["classification"] in {"UNCLASSIFIED", "CLASSIFICATION_CONFLICT"}],
        "owner_contract_gaps": owner_contract_gaps,
        "variant_contract_gaps": variant_contract_gaps,
        "owner_variants": {action: variants_by_action[action]
                            for action in sorted(variants_by_action)},
        "authority_frontier_pass": (
            set(ACTION_BY_ID) == (set(EXPLICIT_DENY_ACTIONS)
                                  | set(NON_AUTHORITY_ACTIONS) | set(owners_by_action))
            and not conflicts and not owner_contract_gaps
            and not variant_contract_gaps and not mismatches and not stale_callsites
            and not unresolved_dynamic
            and all(row["classification"] not in {"UNCLASSIFIED", "CLASSIFICATION_CONFLICT", "AMBIGUOUS"}
                    for row in rows)),
        "primitive_caller_violations": primitive_violations,
        "secure_closed": (
            not direct_api_bypasses and not primitive_violations and not conflicts and not mismatches
            and not unclassified_effectful_actions(rows) and not unresolved_dynamic
            and not any(item["status"] in {"UNWIRED", "BYPASS_RISK",
                                           "NOT_DEMONSTRATED", "PLANNED"}
                        for item in callsites)
            and all(action in EXPLICIT_DENY_ACTIONS for action in unowned_effectful)
            and set(ACTION_BY_ID) == (set(EXPLICIT_DENY_ACTIONS)
                                      | set(NON_AUTHORITY_ACTIONS) | set(owners_by_action))
        ),
    }


def _is_screen_class(node: ast.ClassDef) -> bool:
    return any(_ast_name(base.value if isinstance(base, ast.Subscript) else base)
               .endswith(("Screen", "ModalScreen")) for base in node.bases)


def _issues_from_trees(trees: Sequence[ast.Module]) -> list[dict[str, Any]]:
    """Walk TUIApp, its mixins, and screens those methods construct.

    Screen classes may live in another module. Module-level functions in the
    same trees stay in the walk: the built-in slash commands are functions,
    not methods. A source string passed to ``secure_tui_direct_api_bypasses``
    stays one tree, which is what the single-file audits construct.
    """
    classes: dict[str, ast.ClassDef] = {}
    screens: dict[str, ast.ClassDef] = {}
    for tree in trees:
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            classes[node.name] = node
            if _is_screen_class(node):
                screens[node.name] = node
    app = classes.get("TUIApp")
    if app is None:
        return [{"callsite": "TUIApp", "reason": "Secure entrypoint class is missing"}]

    reachable_nodes: list[tuple[str, ast.AST]] = [("TUIApp", app)]
    for base in app.bases:
        base_name = _ast_name(base.value if isinstance(base, ast.Subscript) else base)
        base_class = classes.get(base_name)
        if base_class is not None and base_class is not app:
            reachable_nodes.append((base_name, base_class))
    for tree in trees:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                reachable_nodes.append((node.name, node))
    reachable_screens: set[str] = set()
    cursor = 0
    while cursor < len(reachable_nodes):
        _, scope_node = reachable_nodes[cursor]
        cursor += 1
        for call in ast.walk(scope_node):
            if not isinstance(call, ast.Call):
                continue
            screen_name = _ast_name(call.func)
            if screen_name in screens and screen_name not in reachable_screens:
                reachable_screens.add(screen_name)
                reachable_nodes.append((screen_name, screens[screen_name]))

    issues = []
    for scope, node in reachable_nodes:
        scope_nodes = list(ast.walk(node))
        # A local name can alias different receivers in different methods of the
        # same scope. Accumulate every sensitive source per name: the set only
        # grows, so the fixed point is reached in a bounded number of passes, and
        # a call through the name counts if any aliased receiver is sensitive.
        aliases: dict[str, set[str]] = {}
        for _ in range(len(scope_nodes)):
            changed = False
            for statement in scope_nodes:
                if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                    continue
                value = statement.value
                source_name = _ast_name(value) if value is not None else ""
                sources = aliases.get(source_name, {source_name}) if source_name else set()
                sensitive = {item for item in sources if _looks_like_sensitive_receiver(item)}
                if not sensitive:
                    continue
                targets = (statement.targets if isinstance(statement, ast.Assign)
                           else [statement.target])
                for target in targets:
                    if isinstance(target, ast.Name):
                        known = aliases.setdefault(target.id, set())
                        if not sensitive <= known:
                            known |= sensitive
                            changed = True
            if not changed:
                break
        for call in scope_nodes:
            if not isinstance(call, ast.Call):
                continue
            target = _ast_name(call.func)
            parts = target.split(".")
            method = parts[-1] if parts else ""
            receiver = ".".join(parts[:-1])
            alias_receivers = aliases.get(receiver, {receiver})
            direct = method in _SECURE_DIRECT_FUNCTIONS
            direct |= any(method in methods and class_name.casefold() in target.casefold()
                          for class_name, methods in _SECURE_DIRECT_API_METHODS.items())
            direct |= any(
                method in methods and _receiver_matches_api(alias_receiver, class_name)
                for class_name, methods in _SECURE_DIRECT_API_METHODS.items()
                for alias_receiver in alias_receivers)
            direct |= method in {"create_subprocess_exec", "Popen", "run", "call", "check_call", "check_output"} \
                and any(token in receiver.casefold() for token in ("asyncio", "subprocess"))
            if direct:
                issues.append({
                    "callsite": f"{scope}:{getattr(call, 'lineno', 0)}:{target}",
                    "reason": "direct effect API call is reachable from a Secure TUI surface",
                })
    return sorted(issues, key=lambda item: item["callsite"])


def secure_tui_direct_api_bypasses(source: str | None = None) -> list[dict[str, Any]]:
    """Find direct calls from TUIApp and screens it actually constructs.

    Low-level Mobile/Bridge/session APIs are intentionally present for isolated
    adapters and tests. They count as a Secure bypass only if a TUI entrypoint
    can reach them without going through a registered owner.

    With no source string, the walk includes ``tui.py`` and the ``tui_*.py``
    modules the app was split into. A source string is parsed alone so the
    single-file audits keep their contract.
    """
    source_path = Path(__file__).resolve().parent / "tui.py"
    try:
        if source is None:
            package = source_path.parent
            paths = [source_path, *sorted(package.glob("tui_*.py"))]
            trees = [ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                     for path in paths]
        else:
            trees = [ast.parse(source, filename=str(source_path))]
    except (OSError, UnicodeError, SyntaxError, TypeError) as exc:
        return [{"callsite": str(source_path), "reason": f"TUI source unavailable ({type(exc).__name__})"}]
    return _issues_from_trees(trees)


def secure_tui_direct_api_bypasses_from_sources(sources: list[str]) -> list[dict[str, Any]]:
    """Audit several source strings as one TUI entrypoint."""
    return _issues_from_trees([ast.parse(source) for source in sources])


def _looks_like_sensitive_receiver(receiver: str) -> bool:
    return any(_receiver_matches_api(receiver, class_name)
               for class_name in _SECURE_DIRECT_API_METHODS)


def _receiver_matches_api(receiver: str, class_name: str) -> bool:
    lowered = receiver.casefold()
    markers = {
        "MobileHost": ("mobile_host", "mobilehost"),
        "ApiKeyStore": ("key_store", "credential_store", "apikeystore"),
        "BridgeClient": ("bridge", "bridge_client"),
        "ChatSessionStore": ("chat_session", "session_store", "chatsessionstore"),
        "MemoryStore": ("memory_store", "memorystore"),
    }
    return any(marker in lowered for marker in markers[class_name])


def _ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def unclassified_effectful_actions(rows: list[dict[str, Any]]) -> list[str]:
    """Return catalog actions lacking a valid, deny, or non-authority state."""
    return [row["action"] for row in rows
            if row["effect"] != "read"
            and row["classification"] in {"UNCLASSIFIED", "CLASSIFICATION_CONFLICT", "AMBIGUOUS"}]


def authority_coverage_snapshot() -> dict[str, Any]:
    """Stable, checked-in snapshot of the catalog authority frontier."""
    report = owner_coverage_report()
    counts = defaultdict(int)
    for row in report["actions"]:
        counts[row["classification"]] += 1
    return {
        "format": "isycode.m15-authority-coverage.v1",
        "summary": {
            "actions": len(report["actions"]),
            "effectful": sum(row["effect"] != "read" for row in report["actions"]),
            "owner_valid": counts["OWNER_VALID"],
            "owner_shared_read": counts["OWNER_SHARED_READ"],
            "owner_variants": counts["OWNER_VARIANTS"],
            "explicit_deny": counts["EXPLICIT_DENY"],
            "secure_excluded": counts["SECURE_EXCLUDED"],
            "unclassified": len(report["unclassified_actions"]),
            "ambiguous": len(report["ambiguous_actions"]),
            "authority_frontier_pass": report["authority_frontier_pass"],
            "secure_tui_closed": report["secure_tui_closed"],
            "secure_closed": report["secure_closed"],
        },
        "actions": report["actions"],
        "owner_action_mismatches": report["owner_action_mismatches"],
        "owner_contract_gaps": report["owner_contract_gaps"],
        "variant_contract_gaps": report["variant_contract_gaps"],
        "ambiguous_actions": report["ambiguous_actions"],
        "unclassified_actions": report["unclassified_actions"],
        "callsites": report["callsites"],
        "secure_tui_direct_api_bypasses": report["secure_tui_direct_api_bypasses"],
        "primitive_caller_violations": report["primitive_caller_violations"],
        "stale_callsites": report["stale_callsites"],
        "request_constructors": report["request_constructors"],
        "dynamic_request_constructors": report["dynamic_request_constructors"],
        "unresolved_dynamic_request_constructors": report["unresolved_dynamic_request_constructors"],
    }


def discover_action_request_constructors() -> list[dict[str, Any]]:
    """Index ActionRequest constructors from source, preserving dynamic fields."""
    package = Path(__file__).resolve().parent
    discovered: list[dict[str, Any]] = []
    for source_path in sorted(package.rglob("*.py")):
        relative = source_path.relative_to(package.parent).as_posix()
        try:
            source = source_path.read_text(encoding="utf-8")
        except UnicodeError:
            discovered.append({"file": relative, "line": 0,
                               "action": None, "owner": None,
                               "parse_error": True})
            continue
        # An unreadable file must not silently become an empty inventory
        # entry: this snapshot is security evidence, so a transient read
        # failure has to surface instead of being recorded as a parse
        # error that could later be committed.
        try:
            tree = ast.parse(source, filename=relative)
        except SyntaxError:
            discovered.append({"file": relative, "line": 0,
                               "action": None, "owner": None,
                               "parse_error": True})
            continue
        parents = {child: parent for parent in ast.walk(tree)
                   for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else "")
            if name != "ActionRequest":
                continue
            action_node = node.args[0] if node.args else next(
                (item.value for item in node.keywords if item.arg == "action_id"), None)
            owner_node = next((item.value for item in node.keywords
                               if item.arg == "execution_owner"), None)
            scope = []
            parent = parents.get(node)
            while parent is not None:
                if isinstance(parent, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope.append(parent.name)
                parent = parents.get(parent)
            callable_name = ".".join((relative.removesuffix(".py").replace("/", "."),
                                      *reversed(scope)))
            discovered.append({
                "file": relative,
                "line": getattr(node, "lineno", 0),
                "callable": callable_name,
                "action": action_node.value if isinstance(action_node, ast.Constant)
                and isinstance(action_node.value, str) else None,
                "owner": owner_node.value if isinstance(owner_node, ast.Constant)
                and isinstance(owner_node.value, str) else None,
            })
    return discovered


def _callsite_exists(declared: str) -> bool:
    """Check that a declared callable is present in the current ISyCode tree."""
    return declared in _defined_callables()


@lru_cache(maxsize=1)
def _defined_callables() -> frozenset[str]:
    package = Path(__file__).resolve().parent
    result: set[str] = set()

    def add_nested(node: ast.AST, prefix: str) -> None:
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not node:
                result.add(f"{prefix}.{child.name}")

    for source_path in package.rglob("*.py"):
        try:
            source = source_path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        # Dropping an unreadable file would make its real callsites look
        # stale (this set is lru_cache'd, so one transient error would
        # poison every later check in the process). A file that cannot be
        # read must fail loudly.
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        module = source_path.relative_to(package.parent).with_suffix("").as_posix().replace("/", ".")
        short_module = module.removeprefix("isycode.")
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result.add(node.name)
                result.add(f"{module}.{node.name}")
                result.add(f"{short_module}.{node.name}")
                add_nested(node, node.name)
            elif isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        result.add(f"{node.name}.{method.name}")
                        result.add(f"{module}.{node.name}.{method.name}")
                        result.add(f"{short_module}.{node.name}.{method.name}")
                        add_nested(method, f"{node.name}.{method.name}")
    return frozenset(result)


def _variants_are_disjoint(action_id: str) -> bool:
    """Require pairwise-distinguishable declared owner predicates."""
    variants = [item for item in OWNER_ACTION_VARIANTS if item.action_id == action_id]
    for index, left in enumerate(variants):
        for right in variants[index + 1:]:
            left_required = dict(left.required_parameters)
            right_required = dict(right.required_parameters)
            shared = set(left_required) & set(right_required)
            if any(left_required[key] != right_required[key] for key in shared):
                continue
            if any(key in right_required for key in left.absent_parameters):
                continue
            if any(key in left_required for key in right.absent_parameters):
                continue
            return False
    return bool(variants)


__all__ = ["authority_coverage_snapshot", "owner_coverage_report", "KNOWN_EFFECT_CALLSITES"]
