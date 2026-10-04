"""The menu kind table keeps every branch that used to return."""
import ast
from pathlib import Path

from isycode.tui_app_menu import MENU_DISPATCH

EXPECTED = {
    "folders_open",
    "folder_add",
    "folder_browse",
    "folder_remove",
    "folder_auto_on",
    "folder_auto_off",
    "integrations_open",
    "harness_open",
    "user_defaults",
    "workspace_config_init",
    "workspace_config_preferences",
    "workspace_config_migrate",
    "workspace_config_migrate_item",
    "workspace_pref_role",
    "workspace_pref_role_clear",
    "user_default_mode",
    "user_default_workspace",
    "user_default_role_save",
    "user_default_role_clear",
    "workspace_mode",
    "coding_toolkit",
    "authority_toggle",
    "authority_saved_grant",
    "bridge_settings",
    "private_access",
    "tailscale_permissions",
    "tailscale_grant",
    "tailscale_refresh",
    "tailscale_install",
    "tailscale_manual",
    "tailscale_login",
    "tailscale_login_check",
    "tailscale_login_cancel",
    "tailscale_serve_enable",
    "tailscale_serve_disable",
    "private_access_back",
    "bridge_toggle",
    "bridge_refresh",
    "security_journal",
    "context_inject",
    "context_project",
    "context_clear",
    "context_info",
    "branch",
    "role_category",
    "command",
    "section",
    "provider_unwired",
    "provider",
    "xai_api_key",
    "xai_session",
    "xai_device",
    "xai_browser",
    "auth_api_key",
    "auth_browser",
    "auth_device",
    "auth_logout",
    "auth_saved",
    "providers_open",
    "roles_open",
    "sounds_toggle",
    "marquee_toggle",
    "reasoning_open",
    "reasoning_select",
    "model",
    "model_list",
    "role_agent",
    "role_motor",
    "shortcuts",
    "mobile_host_status",
    "named_credentials",
    "skill_use",
    "skill_clear",
    "mcp_preset",
    "authority_open",
    "authority_grant_read",
    "authority_revoke_read",
    "authority_provider_grant",
    "authority_provider_revoke",
    "network_action_grant",
    "network_action_revoke",
    "mcp_invoke_grant",
    "mcp_invoke_revoke",
    "gateway_mcp_tool",
    "gateway_semantic_search",
    "broker_preview",
    "broker_provision",
    "broker_manage",
    "lsp_server",
    "lsp_start_grant",
    "lsp_start_revoke",
    "context_menu",
    "credential_add",
    "credential_use_grant",
    "credential_revoke",
    "credential_info",
    "mobile_host_status_refresh",
    "mobile_host_start",
    "chat_session_new",
    "chat_session_resume",
    "mobile_host_new_pin",
    "settings_back",
    "mobile_host_pairing",
    "files",
    "overview",
    "refresh",
    "clear_role",
    "oauth_info",
    "openisy_provider",
    "info",
}

def test_menu_dispatch_keeps_every_extracted_kind():
    assert set(MENU_DISPATCH) == EXPECTED
    assert "section" in MENU_DISPATCH

def test_menu_handlers_exist_once_on_the_app():
    from isycode.tui import TUIApp
    package = Path(__file__).resolve().parents[1] / "src" / "isycode"
    found: dict[str, str] = {}
    for path in sorted(package.glob("tui*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "TUIApp" and not node.name.endswith("Mixin"):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("_menu_"):
                    assert item.name not in found, item.name
                    found[item.name] = node.name
    missing = sorted(set(MENU_DISPATCH.values()) - set(found))
    assert missing == []
    for name in set(MENU_DISPATCH.values()):
        assert callable(getattr(TUIApp, name))
