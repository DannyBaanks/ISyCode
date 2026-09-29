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

    assert "Session delete owner · not connected to session UI" in source
    assert 'row["classification"] in {' in source
    assert '"OWNER_VALID", "OWNER_SHARED_READ", "OWNER_VARIANTS"' in source


def test_authority_settings_never_presents_an_explicit_deny_as_granted():
    from isycode.tui import _authority_action_state

    assert _authority_action_state("mobile.host.start", False) == "DENY · no Secure owner"
    assert _authority_action_state("mobile.host.start", True) == (
        "DENY · no Secure owner · saved grant ignored")
    assert _authority_action_state("provider.request", True) == "grant on"


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
