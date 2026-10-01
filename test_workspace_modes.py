"""Classic mode is a per-workspace grant preset; Sentinel, approvals and journal stay."""
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import LocalWorkspaceReadOwner, ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    return authority, root.resolve()


def _allowed(authority, root, action, target, parameters, owner, approval=False):
    approvals = ActionApprovalStore()
    request = ActionRequest(action, root, target, parameters, execution_owner=owner)
    gate = ProductActionGate(root, authority, owner_id=owner)
    token = approvals.issue(request) if approval else None
    return gate.authorize(request, approvals=approvals, approval=token)[1].allowed


def test_a_new_workspace_has_no_mode_and_legacy_ones_are_security(workspace):
    authority, _ = workspace
    assert authority.mode() is None
    authority.set_grant("workspace.files.read", enabled=False)
    assert authority.mode() == "security"
    authority.set_mode("classic")
    assert authority.mode() == "classic"
    with pytest.raises(ValueError):
        authority.set_mode("yolo")


def test_security_mode_still_denies_everything_without_grants(workspace):
    authority, root = workspace
    authority.set_mode("security")
    outcome = LocalWorkspaceReadOwner(root, authority).execute("workspace.files.read",
                                                               {"path": "app.py"})
    assert outcome.decision == "DENY"


def test_classic_reads_the_workspace_and_still_journals_it(workspace):
    authority, root = workspace
    authority.set_mode("classic")
    outcome = LocalWorkspaceReadOwner(root, authority).execute("workspace.files.read",
                                                               {"path": "app.py"})
    assert outcome.decision == "ALLOW" and "x = 1" in outcome.text
    assert ActionAuditJournal(root).verify().receipts == 1
    assert LocalWorkspaceReadOwner(root, authority).execute(
        "workspace.files.read", {"path": ".env"}).decision == "DENY"
    assert LocalWorkspaceReadOwner(root, authority).execute(
        "workspace.files.read", {"path": "../outside"}).decision == "DENY"


def test_classic_edits_still_need_the_diff_approval(workspace):
    authority, root = workspace
    authority.set_mode("classic")
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)
    preview = owner.preview("app.py", "x = 2\n")
    assert owner.apply(preview, None).decision == "DENY"
    assert owner.apply(preview, approvals.issue(preview.request)).decision == "ALLOW"
    assert (root / "app.py").read_text() == "x = 2\n"


def test_classic_talks_only_to_known_provider_hosts(workspace):
    authority, root = workspace
    authority.set_mode("classic")
    assert _allowed(authority, root, "provider.request", "api.openai.com",
                    {"url": "https://api.openai.com/v1"}, "provider_network")
    assert not _allowed(authority, root, "provider.request", "evil.example.com",
                        {"url": "https://evil.example.com/v1"}, "provider_network")


def test_classic_uses_saved_keys_only_for_known_services(workspace):
    authority, root = workspace
    authority.set_mode("classic")
    assert _allowed(authority, root, "credentials.use", "openai",
                    {"service": "openai", "consumer": "provider.request"}, "credential_use")
    assert not _allowed(authority, root, "credentials.use", "evil",
                        {"service": "evil", "consumer": "provider.request"}, "credential_use")


@pytest.mark.parametrize("action, target, parameters, owner", [
    ("mobile.host.start", "127.0.0.1:8765",
     {"bind": "127.0.0.1", "port": 8765, "transport": "loopback"}, "mobile_host"),
    ("mcp.invoke", "gateway", {}, "gateway_mcp"),
    ("workspace.command.run", "/usr/bin/echo", {"argv": ["echo"]}, "workspace_command"),
    ("bridge.connect", "bridge", {}, "bridge"),
])
def test_classic_does_not_imply_integrations_or_denied_actions(workspace, action, target,
                                                               parameters, owner):
    authority, root = workspace
    authority.set_mode("classic")
    assert not _allowed(authority, root, action, target, parameters, owner, approval=True)


def test_classic_preset_is_never_written_into_the_explicit_policy(workspace):
    authority, _ = workspace
    authority.set_mode("classic")
    assert authority.policy()["grants"] == {}
    assert authority.effective_policy()["grants"]["workspace.files.read"]["enabled"] is True
    authority.set_mode("security")
    assert "workspace.files.read" not in authority.effective_policy()["grants"]


def test_mode_screen_defaults_to_security_on_escape_and_offers_classic(tmp_path):
    import asyncio

    from textual.app import App
    from isycode.tui import WorkspaceModeScreen

    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(WorkspaceModeScreen(tmp_path), results.append)

    async def scenario(keys):
        async with Host().run_test() as pilot:
            await pilot.pause()
            for key in keys:
                await pilot.press(key)
            await pilot.pause()

    asyncio.run(scenario(["escape"]))
    asyncio.run(scenario(["enter"]))
    asyncio.run(scenario(["down", "enter"]))
    assert results == ["security", "classic", "security"]


def test_tui_checks_use_effective_grants_and_writes_use_explicit_ones():
    import ast

    source = (Path(__file__).parent / "isycode" / "tui.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: ast.get_source_segment(source, node) for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_workspace_chat_tools_enabled", "_workspace_write_tool_enabled",
                 "_sessions_enabled", "_initialize_workspace", "_open_authority_menu"):
        assert "effective_policy()" in methods[name], name
        assert ".policy()" not in methods[name], name
    assert "effective_policy" not in methods["_change_provider_network_grant"]
