"""Static UI mediation witnesses for the optional private Tailscale wizard."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "isycode" / "tui.py"


def _surfaces() -> list[Path]:
    return [SOURCE, *sorted(SOURCE.parent.glob("tui_*.py"))]


def _surface_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _surfaces())


def _owned():
    methods = {}
    sources = {}
    for path in _surfaces():
        text = path.read_text(encoding="utf-8")
        module = ast.parse(text)
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "TUIApp" and not node.name.endswith("Mixin"):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods[item.name] = item
                    sources[item.name] = text
    return sources, methods


def _app_methods():
    return _owned()[1]


def _segment(name: str) -> str:
    sources, methods = _owned()
    return ast.get_source_segment(sources[name], methods[name])


def _calls(method):
    return [node.func.attr if isinstance(node.func, ast.Attribute)
            else node.func.id if isinstance(node.func, ast.Name) else ""
            for node in ast.walk(method) if isinstance(node, ast.Call)]


def test_private_access_is_reachable_from_settings_and_open_is_read_only():
    source = _surface_text()
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
        assert "_await_screen" in calls
        assert "issue" in calls
        assert "to_thread" in calls


def test_tailscale_serve_targets_mobile_host_and_mounted_health_path():
    method = _app_methods()["_run_tailscale_serve"]
    adapter = next(node for node in ast.walk(method)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name)
                   and node.func.id == "TailscaleAdapter")
    kwargs = {item.arg: item.value for item in adapter.keywords}
    assert ast.literal_eval(kwargs["gateway_url"]) == "http://127.0.0.1:8765"
    assert ast.literal_eval(kwargs["gateway_port"]) == 8765
    assert ast.literal_eval(kwargs["gateway_health_path"]) == "/isycode/v1/health"

    owner = next(node for node in ast.walk(method)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "TailscaleServeOwner")
    owner_kwargs = {item.arg: item.value for item in owner.keywords}
    assert isinstance(owner_kwargs["route_id"], ast.Name)
    assert owner_kwargs["route_id"].id == "MOBILE_HOST_ROUTE_ID"
    assert ast.literal_eval(owner_kwargs["service_label"]) == "Mobile Host"


def test_serve_failure_reports_owner_validation_reason_without_command_output():
    source = _segment("_run_tailscale_serve")
    assert "isinstance(exc, ValueError)" in source
    assert "str(exc)[:180]" in source
    assert "No route change was approved" in source


def test_tui_does_not_run_tailscale_or_package_commands_directly():
    source = _surface_text()
    methods = _app_methods()
    names = ["on_mount", "_open_settings_menu", "_refresh_private_access",
             "_select_menu_entry"]
    names.extend(name for name in methods if name.startswith("_menu_"))
    for name in names:
        calls = _calls(methods[name])
        assert "Popen" not in calls, name
        assert "subprocess" not in calls, name
        assert "runner" not in calls, name
    assert "shell=True" not in source


def test_authority_grant_is_separately_confirmed_and_narrowly_scoped():
    methods = _app_methods()
    calls = _calls(methods["_change_tailscale_grant"])
    source_text = _surface_text()
    assert "_await_screen" in calls
    assert "set_grant" in calls
    assert "executables" in source_text
    assert "one-use approval" in source_text


def test_manual_path_is_documented_without_starting_tailscale():
    methods = _app_methods()
    calls = _calls(methods["_show_tailscale_manual_steps"])
    assert "_await_screen" in calls
    assert "tailscale.com/docs/install/linux" in _surface_text()
    assert "tailscale" not in calls



def test_serve_route_lifetime_policy_is_explicit_and_never_unapproved():
    """Exit never disables Serve without approval; Settings says the route persists."""
    methods = _app_methods()
    assert not set(_calls(methods["on_unmount"])) & {
        "disable", "preview_disable", "_run_tailscale_serve"}
    refresh = _segment("_refresh_private_access")
    assert "Route stays on after ISyCode exits" in refresh
    start = _segment("_start_mobile_host")
    assert "already points here" in start


def test_linux_operator_guidance_is_text_only_and_shown_on_failures():
    for name in ("_run_tailscale_serve", "_check_tailscale_login"):
        assert "LINUX_OPERATOR_HINT" in _segment(name), name
    package = Path(__file__).resolve().parents[1] / "src" / "isycode"
    for module in ("tailscale.py", "tailscale_login.py", "tailscale_serve.py", "tailscale_read.py"):
        tree = ast.parse((package / module).read_text(encoding="utf-8"))
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        assert "sudo" not in literals and "/usr/bin/sudo" not in literals, module


def test_mobile_host_status_reports_a_saved_private_route():
    segment = _segment("_render_mobile_host_status")
    assert "Tailscale Serve is not modified" not in segment
    assert "route_url(" in segment
