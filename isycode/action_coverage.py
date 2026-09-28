"""Reproducible, explicit inventory of action owners and known effect callsites.

This is a contract report, not a source-code oracle: callsites are named
deliberately and reviewed alongside the owners. A missing declaration is a
coverage gap, never an implicit grant or owner.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from isycode.actions import ACTION_CATALOG
from isycode.action_runtime import OWNER_ACTIONS


# These multiple bindings are deliberate child reads within an independently
# bound operation. Other multi-owner action registrations are reported as
# ambiguous until their execution scopes are made mutually exclusive.
ALLOWED_SHARED_ACTION_OWNERS = {
    "workspace.files.read": frozenset({
        "workspace_read", "lsp_symbols", "broker_preview", "broker_provision",
    }),
}

# Audited effect-producing callsites. Status is explicit because there is no
# reliable automatic way to infer whether an arbitrary Python function is a
# product execution owner.
KNOWN_EFFECT_CALLSITES = (
    ("provider.request", "TUIApp._send_prompt", "provider_network", "COVERED"),
    ("workspace.files.read", "TUIApp._inject_agent_context", "workspace_read", "COVERED"),
    ("workspace.files.read", "TUIApp._read_workspace_file", "workspace_read", "COVERED"),
    ("mcp.invoke", "GatewayMCPInvocationOwner.invoke", "gateway_mcp", "COVERED"),
    ("gateway.semantic.read", "GatewaySemanticOwner.call", "gateway_semantic", "COVERED"),
    ("lsp.start", "LPSSymbolOwner.query", "lsp_symbols", "COVERED"),
    ("broker.build", "BrokerProvisionOwner.execute", "broker_provision", "COVERED"),
    ("broker.start", "BrokerProvisionOwner.execute", "broker_provision", "COVERED"),
    ("session.delete", "SessionDeleteOwner.delete", "session_delete", "COVERED"),
    ("mobile.host.start", "MobileHost.start", "", "UNWIRED"),
    ("mobile.host.stop", "MobileHost.stop", "", "UNWIRED"),
    ("mobile.pair", "MobileHost._pair", "", "UNWIRED"),
    ("credentials.add", "ApiKeyStore.issue", "", "UNWIRED"),
    ("credentials.revoke", "ApiKeyStore.revoke", "", "UNWIRED"),
    ("bridge.connect", "BridgeClient.hello", "", "BLOCKED_BY_DESIGN"),
    ("bridge.connect", "BridgeClient.heartbeat", "", "UNWIRED"),
    ("bridge.connect", "BridgeClient.goodbye", "", "UNWIRED"),
    ("bridge.peek", "BridgeClient.peek", "", "BLOCKED_BY_DESIGN"),
    ("bridge.lease.claim", "BridgeClient.claim", "", "BLOCKED_BY_DESIGN"),
    ("bridge.lease.release", "BridgeClient.release", "", "UNWIRED"),
    ("bridge.send", "BridgeClient.send", "", "BLOCKED_BY_DESIGN"),
    ("credentials.add", "TUIApp._save_provider_key", "", "BLOCKED_BY_DESIGN"),
    ("credentials.add", "TUIApp._open_credentials_menu", "", "BLOCKED_BY_DESIGN"),
    ("session.create", "TUIApp._persist_chat_message", "", "BLOCKED_BY_DESIGN"),
    ("session.create", "TUIApp._show_chat_sessions", "", "BLOCKED_BY_DESIGN"),
    ("session.create", "ChatSessionStore.create", "", "UNWIRED"),
    ("session.create", "ChatSessionStore.append", "", "UNWIRED"),
    ("session.resume", "ChatSessionStore.load", "", "UNWIRED"),
    ("session.create", "ChatSessionStore.rename", "", "UNWIRED"),
    ("session.create", "ChatSessionStore.fork", "", "UNWIRED"),
    ("desktop.file_picker", "TUIApp._inject_agent_context", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "TUIApp._open_broker_preview", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "TUIApp._provision_broker", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "TUIApp._readme_cmd", "", "BLOCKED_BY_DESIGN"),
    ("desktop.file_picker", "file_picker.choose_context_file", "", "BYPASS_RISK"),
    ("desktop.file_picker", "file_picker.choose_workspace_file", "", "BYPASS_RISK"),
    ("desktop.file_picker", "file_picker.choose_workspace_directory", "", "BYPASS_RISK"),
    ("clipboard.copy", "TUIApp._on_button_pressed", "", "BLOCKED_BY_DESIGN"),
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
    conflicts = []
    for action, owners in sorted(owners_by_action.items()):
        actual = frozenset(owners)
        permitted = ALLOWED_SHARED_ACTION_OWNERS.get(action)
        if len(actual) > 1 and actual != permitted:
            conflicts.append({"action": action, "owners": sorted(actual)})
    rows = []
    for spec in ACTION_CATALOG:
        owners = sorted(owners_by_action.get(spec.id, []))
        if len(owners) > 1 and frozenset(owners) not in {
                ALLOWED_SHARED_ACTION_OWNERS.get(spec.id, frozenset())}:
            status = "BYPASS_RISK"
        elif owners:
            status = "COVERED"
        else:
            status = "UNWIRED"
        rows.append({"action": spec.id, "effect": spec.effect,
                     "approval_required": spec.approval_required,
                     "owners": owners, "status": status})
    effectful = [row for row in rows if row["effect"] != "read"]
    unowned_effectful = [row["action"] for row in effectful if not row["owners"]]
    callsites = [{"action": action, "callsite": callsite,
                  "owner": owner or None, "status": status}
                 for action, callsite, owner, status in KNOWN_EFFECT_CALLSITES]
    return {
        "actions": rows,
        "callsite_count": len(callsites),
        "callsites": list(callsites),
        "owner_action_mismatches": sorted(set(mismatches + unknown_actions)),
        "ambiguous_actions": conflicts,
        "unowned_effectful_actions": unowned_effectful,
        "effectful_callsites_without_mediation": [
            item for item in callsites if item["status"] in {"UNWIRED", "BYPASS_RISK", "NOT_DEMONSTRATED"}
        ],
        "secure_closed": not unowned_effectful and not conflicts and not any(
            item["status"] in {"UNWIRED", "BYPASS_RISK", "NOT_DEMONSTRATED"}
            for item in callsites),
    }


__all__ = ["owner_coverage_report", "KNOWN_EFFECT_CALLSITES"]
