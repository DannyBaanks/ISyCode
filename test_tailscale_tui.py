"""Static UI mediation witnesses for the optional private Tailscale wizard."""
import ast
from pathlib import Path

SOURCE = Path(__file__).parent / "isycode" / "tui.py"


def _app_methods():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    return {node.name: node for node in app.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _calls(method):
    return [node.func.attr if isinstance(node.func, ast.Attribute)
            else node.func.id if isinstance(node.func, ast.Name) else ""
            for node in ast.walk(method) if isinstance(node, ast.Call)]


def test_private_access_is_reachable_from_settings_and_open_is_read_only():
    source = SOURCE.read_text(encoding="utf-8")
    methods = _app_methods()
    assert '"private_access"' in source
    assert "TailscaleReadOwner" in _calls(methods["_refresh_private_access"])
    assert not (set(_calls(methods["_refresh_private_access"])) & {
        "prepare", "stage", "install", "begin_login", "enable", "disable"})
    assert "run_worker" in _calls(methods["_open_private_access_menu"])


def test_package_login_and_serve_changes_need_ui_confirmation_and_registered_owners():
    methods = _app_methods()
    for name, owner in (
        ("_run_tailscale_install", "TailscalePackageInstallOwner"),
        ("_run_tailscale_login", "TailscaleLoginOwner"),
        ("_run_tailscale_serve", "TailscaleServeOwner"),
    ):
        calls = _calls(methods[name])
        assert owner in calls
        assert "push_screen_wait" in calls
        assert "issue" in calls
        assert "to_thread" in calls


def test_tui_does_not_run_tailscale_or_package_commands_directly():
    source = SOURCE.read_text(encoding="utf-8")
    methods = _app_methods()
    for name in ("on_mount", "_open_settings_menu", "_refresh_private_access",
                 "_select_menu_entry"):
        calls = _calls(methods[name])
        assert "Popen" not in calls
        assert "subprocess" not in calls
        assert "runner" not in calls
    assert "shell=True" not in source


def test_authority_grant_is_separately_confirmed_and_narrowly_scoped():
    methods = _app_methods()
    calls = _calls(methods["_change_tailscale_grant"])
    source_text = SOURCE.read_text(encoding="utf-8")
    assert "push_screen_wait" in calls
    assert "set_grant" in calls
    assert "executables" in source_text
    assert "one-use approval" in source_text


def test_manual_path_is_documented_without_starting_tailscale():
    methods = _app_methods()
    calls = _calls(methods["_show_tailscale_manual_steps"])
    assert "push_screen_wait" in calls
    assert "tailscale.com/docs/install/linux" in SOURCE.read_text(encoding="utf-8")
    assert "tailscale" not in calls
