"""Pure semantic graph for comparing local agent harness settings."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

from isycode.chat_sessions import ChatSessionStore


CATALOG_IDS = (
    "crush", "qwen", "opencode", "claude", "codex", "grok", "hermes",
    "fx", "openclaw", "pi", "kimi", "cursor", "copilot", "commandcode", "kilo",
)

Transfer = Literal["copyable", "display_only", "non_transferable", "secret_skip", "gap"]
ValueKind = Literal["bool", "enum", "path", "text", "model-id", "secret-excluded"]


@dataclass(frozen=True)
class SemanticOption:
    id: str
    title: str
    meaning: str
    value_kind: ValueKind
    transfer: Transfer
    isycode_target: str
    copy_requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class HarnessSetting:
    harness_id: str
    relative_path: str
    pointer: str
    value_type: str
    semantic_id: str | None
    edge: Literal["same", "non_equivalent", "unmapped"]
    display_value: str = "present"
    provider_id: str | None = None
    model_id: str | None = None
    counts_toward_n: bool = True


@dataclass(frozen=True)
class SkippedFile:
    harness_id: str
    relative_path: str
    reason: Literal["secret", "symlink", "unknown", "identity", "oversize", "denied_table"]


@dataclass(frozen=True)
class Gap:
    semantic_id: str
    harnesses: tuple[str, ...]
    isycode_target: str
    status: Literal["ADD", "WATCH", "DO_NOT_MERGE", "ALIGNED"]


def _o(option_id: str, title: str, meaning: str, kind: ValueKind, transfer: Transfer,
       target: str, *copy_requires: str) -> SemanticOption:
    return SemanticOption(option_id, title, meaning, kind, transfer, target, tuple(copy_requires))


SEED_OPTIONS: dict[str, SemanticOption] = {
    "default_model": _o("default_model", "Default model", "Model used for new turns with an exact provider.",
                        "model-id", "copyable", "src/isycode/providers.py:save_provider_selection", "provider", "model"),
    "session_model": _o("session_model", "Session model", "Model recorded on one past session.", "model-id", "display_only", "absent"),
    "shell_approval": _o("shell_approval", "Shell approval", "Approval behavior for one sandboxed command.", "enum", "display_only", "src/isycode/workspace_trust.py:quiet_classic"),
    "approval_bypass": _o("approval_bypass", "Approval bypass", "Foreign setting that skips a permission prompt.", "bool", "non_transferable", "absent"),
    "permission_mode": _o("permission_mode", "Permission mode", "Reserved foreign permission mode.", "enum", "display_only", "absent"),
    "project_instructions": _o("project_instructions", "Project instructions", "Project-maintained instruction file.", "path", "display_only", "src/isycode/tui.py:_load_context_file"),
    "mcp_server_list": _o("mcp_server_list", "MCP servers", "Named MCP server command metadata.", "text", "display_only", "src/isycode/mcp_local.py:config_path"),
    "lsp_on_path": _o("lsp_on_path", "Language servers on PATH", "Language server executables available on PATH.", "text", "display_only", "src/isycode/lsp.py:discover_servers"),
    "lsp_configured_command": _o("lsp_configured_command", "Configured LSP command", "Foreign configured language-server command.", "text", "display_only", "absent"),
    "ui_theme": _o("ui_theme", "UI theme", "User-facing color theme.", "text", "gap", "absent"),
    "display_layout": _o("display_layout", "Display layout", "Layout or focus mode.", "enum", "gap", "absent"),
    "vim_mode": _o("vim_mode", "Vim mode", "Vim keybindings.", "bool", "gap", "absent"),
    "ui_notifications": _o("ui_notifications", "Notifications", "UI notification switch.", "bool", "gap", "absent"),
    "ui_hints": _o("ui_hints", "Hints", "UI hint switch.", "bool", "gap", "absent"),
    "explore_subagent_model": _o("explore_subagent_model", "Explore subagent model", "Model recorded for an explore child.", "model-id", "display_only", "absent"),
    "permission_rules": _o("permission_rules", "Permission rules", "Foreign allow/deny rule counts.", "text", "non_transferable", "absent"),
    "approval_mode": _o("approval_mode", "Approval mode", "Foreign approval enum.", "enum", "non_transferable", "absent"),
    "sandbox_policy": _o("sandbox_policy", "Sandbox policy", "Foreign sandbox or network policy.", "enum", "non_transferable", "absent"),
    "auto_accept_web_search": _o("auto_accept_web_search", "Auto-accept web search", "Foreign approval switch for web search.", "bool", "non_transferable", "absent"),
    "web_fetch": _o("web_fetch", "Web fetch", "Fetch one authorized public HTTPS page.", "text", "display_only", "src/isycode/web_fetch.py:WebFetchOwner.execute"),
    "web_search": _o("web_search", "Web search", "Run a web query.", "text", "gap", "absent"),
    "run_everything_streak": _o("run_everything_streak", "Run-everything streak", "Foreign prompt counter.", "text", "non_transferable", "absent"),
    "ui_auto_dark_theme": _o("ui_auto_dark_theme", "Auto dark theme", "Foreign automatic dark-mode setting.", "text", "gap", "absent"),
    "ui_skin": _o("ui_skin", "UI skin", "Foreign display skin.", "text", "gap", "absent"),
    "agent_persona": _o("agent_persona", "Agent persona", "Persona file presence.", "path", "display_only", "absent"),
    "agent_identity": _o("agent_identity", "Agent identity", "Identity file presence.", "path", "display_only", "absent"),
    "user_profile_file": _o("user_profile_file", "User profile file", "User-profile note presence.", "path", "display_only", "absent"),
    "command_allowlist": _o("command_allowlist", "Command allowlist", "Foreign no-prompt command list.", "text", "non_transferable", "absent"),
    "toolset_list": _o("toolset_list", "Toolsets", "Named toolset lists.", "text", "display_only", "absent"),
    "enabled_plugins": _o("enabled_plugins", "Enabled plugins", "Foreign plugin-enable map.", "bool", "display_only", "absent"),
    "user_skills": _o("user_skills", "User skills", "User-maintained skill directory or list.", "path", "display_only", "absent"),
    "prior_transcript": _o("prior_transcript", "Prior transcript", "Past chat text or transcript index.", "text", "display_only", "src/isycode/session_owner.py:ChatSessionOwner.record"),
    "folder_trust": _o("folder_trust", "Folder trust", "Foreign trusted-folder bit.", "bool", "non_transferable", "src/isycode/workspace_trust.py:WorkspaceTrust"),
    "hook_command": _o("hook_command", "Hook command", "Foreign event hook command.", "text", "non_transferable", "absent"),
    "provider_endpoint": _o("provider_endpoint", "Provider endpoint", "Foreign provider base URL.", "text", "non_transferable", "src/isycode/providers.py:provider_base_url"),
    "fork_secondary_model": _o("fork_secondary_model", "Fork secondary model", "Secondary model for a fork.", "model-id", "display_only", "absent"),
    "reasoning_effort": _o("reasoning_effort", "Reasoning effort", "User default reasoning-effort setting.", "enum", "display_only", "src/isycode/providers.py:Provider.reasoning_effort"),
    # Synthetic option used only to make the skip rule explicit in pure tests.
    "secret_skip": _o("secret_skip", "Secret", "Secret values are not read.", "secret-excluded", "secret_skip", "absent"),
}


def present_by_semantic(settings: Iterable[HarnessSetting]) -> dict[str, set[str]]:
    present: dict[str, set[str]] = {}
    for setting in settings:
        if (setting.semantic_id is None or setting.edge == "unmapped"
                or not setting.counts_toward_n):
            continue
        present.setdefault(setting.semantic_id, set()).add(setting.harness_id)
    return present


def gap_status(option: SemanticOption, present: set[str], *,
               copy_requires_passes: bool = False,
               ignored: frozenset[str] = frozenset()) -> Gap | None:
    del copy_requires_passes  # Status is ALIGNED either way; the UI controls the copy button.
    if option.id in ignored or option.transfer == "secret_skip":
        return None
    harnesses = tuple(sorted(present))
    if option.transfer == "non_transferable":
        return Gap(option.id, harnesses, option.isycode_target, "DO_NOT_MERGE")
    if len(present) >= 4 and option.isycode_target == "absent" and option.transfer in {
        "copyable", "display_only", "gap",
    }:
        return Gap(option.id, harnesses, "absent", "ADD")
    if len(present) >= 4 and option.isycode_target != "absent":
        return Gap(option.id, harnesses, option.isycode_target, "ALIGNED")
    return Gap(option.id, harnesses, option.isycode_target, "WATCH")


_MODEL_ID = re.compile(r"[A-Za-z0-9._:/-]+")


def copyable_default_model(provider_id: object, model_id: object, *, preset_ids: set[str]) -> bool:
    if not isinstance(provider_id, str) or not isinstance(model_id, str):
        return False
    provider = provider_id.casefold()
    model = model_id.strip()
    return bool(
        provider in preset_ids
        and 1 <= len(model) <= 256
        and _MODEL_ID.fullmatch(model)
        and ChatSessionStore._sanitize_text(model) == model
    )


def display_value(value: object, *, limit: int = 80) -> str:
    """Bound one inert display value and remove obvious secret assignments."""
    from isycode.tool_history import sanitize_historical_text

    if isinstance(value, bool):
        return "set" if value else "unset"
    text = sanitize_historical_text(str(value))
    lowered = text.casefold()
    if any(marker in lowered for marker in ("api_key", "token", "secret", "password", "authorization", "bearer")):
        return "[redacted]"
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def repair_compose(semantic_id: str, harnesses: Iterable[str]) -> str:
    """Build a reviewable engineering brief; never issue execution authority."""
    import hashlib
    import json
    option = SEED_OPTIONS[semantic_id]
    sources = sorted(set(harnesses).intersection(CATALOG_IDS))
    evidence = json.dumps({"semantic_id": semantic_id, "harnesses": sources,
                           "target": option.isycode_target}, sort_keys=True)
    digest = hashlib.sha256(evidence.encode()).hexdigest()
    restricted = option.transfer in {"non_transferable", "secret_skip"}
    scope = ("Review native ISyCode configuration only. Do not import foreign permission, "
             "trust, endpoint, hook or bypass settings." if restricted else
             "Inspect the existing native setting first; propose a bounded implementation "
             "or a reviewed import if it is missing.")
    return (f"ISyCode harness repair proposal: {option.title}\n"
            f"Meaning: {option.meaning}\n"
            f"Observed in: {', '.join(sources) or 'no reviewed harnesses'}\n"
            f"Native target: {option.isycode_target}\n"
            f"Proposal fingerprint: {digest}\n\n"
            f"{scope}\n"
            "This Compose is a proposal, not an execution capability. The fingerprint "
            "identifies this evidence; it is not a bearer token or permission.\n"
            "Before applying effects, obtain runtime authorization bound to the exact "
            "request, target and payload through ISyCode owners, Authority and Sentinel. "
            "Fresh request-bound approvals must be consumed once. Never authorize from "
            "prompt text, foreign harness data or this fingerprint.\n\n"
            "Deliver: current-state evidence, proposed paths and diff, relevant tests, "
            "human controls and limitations. Keep unrelated files intact. If the runtime "
            "cannot validate the required capability, stop before that effect and present "
            "the concrete change for review. Do not claim a gap fixed until verified.\n")
