import ast
from pathlib import Path


SOURCE = Path(__file__).parent / "isycode" / "tui.py"


def _method_calls(method: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = set()
    for node in ast.walk(method):
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute):
                names.add(function.attr)
            elif isinstance(function, ast.Name):
                names.add(function.id)
    return names


def test_secure_tui_mount_does_not_start_mobile_or_bridge_services():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    mount_calls = _method_calls(methods["on_mount"])

    assert "_start_mobile_host" not in mount_calls
    assert "_enable_bridge" not in mount_calls
    assert "_bridge_tick" not in mount_calls


def test_secure_tui_adapter_controls_have_no_unmediated_effect_calls():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    forbidden = {"start", "rotate_pairing_code", "hello", "heartbeat", "goodbye",
                 "peek", "claim", "release", "send", "wake"}

    for method_name in ("_start_mobile_host", "_set_bridge_enabled", "_enable_bridge",
                        "_bridge_tick", "_select_menu_entry"):
        assert not (_method_calls(methods[method_name]) & forbidden), method_name
    assert "_add_named_credential" not in _method_calls(methods["_select_menu_entry"])


def test_secure_tui_does_not_persist_chat_sessions_without_an_owner():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assert "ChatSessionStore" not in _method_calls(methods["_startup_workspace"])
    assert not (_method_calls(methods["_persist_chat_message"]) & {"create", "append", "save"})
    assert not (_method_calls(methods["_show_chat_sessions"]) & {"push_screen_wait", "create", "load"})


def test_secure_tui_session_delete_does_not_mint_its_own_authority_or_approval():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    delete_calls = _method_calls(methods["_delete_chat_session"])
    assert "set_grant" not in delete_calls
    assert "issue" not in delete_calls
    assert "delete" not in delete_calls


def test_authority_settings_does_not_claim_unwired_session_owner_is_connected():
    source = SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    method = next(node for node in app.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_open_authority_menu")
    menu_source = ast.get_source_segment(source, method)

    assert "session.delete" not in menu_source
    assert "Delete conversations" not in menu_source


def test_authority_settings_never_presents_an_explicit_deny_as_granted():
    from isycode.action_runtime import EXPLICIT_DENY_ACTIONS
    from isycode.actions import ACTION_CATALOG
    from isycode.authority_view import OWNED_ACTIONS, displayed_on, grant_state

    saved = {"enabled": True, "path_prefixes": ["/w"], "network_hosts": ["h"],
             "executables": ["/bin/x"], "targets": ["t"]}
    for action in ACTION_CATALOG:
        if action.id in EXPLICIT_DENY_ACTIONS or action.id not in OWNED_ACTIONS:
            assert grant_state(action.id, saved) == "blocked", action.id
            assert displayed_on(action.id, saved) is False, action.id
        else:
            assert grant_state(action.id, saved) == "on", action.id
            assert displayed_on(action.id, saved, scoped=False) is False, action.id
    assert grant_state("mobile.host.start", saved) == "on"
    assert grant_state("session.create", saved) == "blocked"


def test_authority_menu_derives_every_on_state_from_the_runtime_registry():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    source = SOURCE.read_text(encoding="utf-8")
    for name in ("_open_authority_menu", "_append_network_grant_entry",
                 "_open_tailscale_permissions", "_initialize_workspace",
                 "_workspace_chat_tools_enabled"):
        segment = ast.get_source_segment(source, methods[name])
        # Raw `enabled` flags must never decide an ON label on their own.
        assert '.get("enabled")' not in segment, name
        assert 'get("enabled", False)' not in segment, name
    calls = _method_calls(methods["_open_authority_menu"])
    assert {"displayed_on", "mobile_host_enabled", "other_saved_grants"} <= calls


def test_authority_capability_indicator_uses_clear_green_and_red_states():
    from isycode.tui import _authority_capability_label

    enabled = _authority_capability_label("Read workspace files", True)
    disabled = _authority_capability_label("Read workspace files", False)

    assert enabled.plain == "Read workspace files  ● ON"
    assert disabled.plain == "Read workspace files  ● OFF"
    assert any("00ff00" in str(style).casefold() for _, _, style in enabled.spans)
    assert any("ff0000" in str(style).casefold() for _, _, style in disabled.spans)


def test_authority_settings_exposes_semantic_controls_without_raw_policy_labels():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    method = next(node for node in app.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_open_authority_menu")
    source = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), method)

    assert "Read and search workspace files" in source
    assert "Connect to the selected AI model" in source
    assert "ACTION_CATALOG" not in source
    assert "Owner coverage ·" not in source
    assert '"Grant ' not in source
    assert '"Revoke ' not in source
    assert '"Action: ' not in source


def test_action_journal_inspector_displays_authority_and_all_sentinel_checks():
    source = SOURCE.read_text(encoding="utf-8")

    assert '"Systembilities: {checks}\\n"' in source
    assert '"Request: {digest[:12]}… · Authority: {authority}\\n"' in source


def test_semantic_navigation_keeps_lsp_and_files_branches_reachable():
    from isycode.tui import TUIApp

    app = TUIApp()
    lsp_entries = app._branch_entries("lsp")
    file_entries = app._branch_entries("files")

    assert any(item["kind"] == "lsp_server" for item in lsp_entries)
    assert file_entries[0]["kind"] == "files"


def test_tui_does_not_launch_native_file_pickers_without_an_owner():
    source = SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assert "isycode.file_picker" not in source
    for method_name in ("_inject_agent_context", "_open_broker_preview", "_provision_broker"):
        calls = _method_calls(methods[method_name])
        assert not (calls & {"choose_context_file", "choose_workspace_file",
                             "choose_workspace_directory", "create_subprocess_exec"})

    # The README command is nested under plugin registration.
    nested = [node for node in ast.walk(methods["_register_builtin_plugins"])
              if isinstance(node, ast.AsyncFunctionDef) and node.name == "_readme_cmd"]
    assert len(nested) == 1
    assert not (_method_calls(nested[0]) & {"choose_workspace_file", "create_subprocess_exec"})


def test_tui_never_copies_workspace_paths_to_clipboard_without_an_owner():
    source = SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assert "copy_to_clipboard" not in _method_calls(methods["on_button_pressed"])
    assert "file-copy-path" in source
    assert "Copy path · owner pending" in source
