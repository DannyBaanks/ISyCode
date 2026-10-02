"""Quiet Classic is a human trust decision, not a bypass and not a model tool."""
import ast
import asyncio
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.actions import ACTION_BY_ID
from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner
from isycode.headless import available_tools
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_trust import (
    ACCEPT_PHRASE, WorkspaceTrust, modal_required, onboarding_brief, quiet_classic,
)
from isycode.workspace_write import WorkspaceWriteOwner

_COMMANDS = importlib.util.spec_from_file_location(
    "isycode_command_tests", Path(__file__).with_name("test_command_runner.py"))
_COMMAND_MODULE = importlib.util.module_from_spec(_COMMANDS)
_COMMANDS.loader.exec_module(_COMMAND_MODULE)
FAKE_BWRAP = _COMMAND_MODULE.FAKE_BWRAP


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("ISYCODE_STATE_HOME", raising=False)
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("", encoding="utf-8")
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    for index in range(10):
        (root / f"read{index}.txt").write_text(f"value {index}\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("classic")
    return authority, root.resolve()


def _trust(authority) -> None:
    WorkspaceTrust().accept(authority, ACCEPT_PHRASE)


def test_brief_names_the_root_the_provider_and_the_limit(project):
    authority, root = project
    text = onboarding_brief(root=root, mode="Classic", provider="openai",
                            sends_workspace_context=True)
    assert str(root) in text
    assert "Classic" in text and "openai" in text
    assert "sent to that provider" in text
    assert "effect budget" in text
    assert "without a sandbox" in text
    assert "revoked" in text
    assert "not a permanent approval" in text


def test_wrong_phrase_broad_root_and_inside_state_do_not_trust(project, monkeypatch):
    authority, root = project
    trust = WorkspaceTrust()
    with pytest.raises(ValueError):
        trust.accept(authority, "trust everything")
    assert not trust.trusted(authority)
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "state"))
    inside = WorkspaceTrust()
    with pytest.raises(ValueError):
        inside.accept(authority, ACCEPT_PHRASE)
    assert not inside.trusted(authority)
    monkeypatch.setenv("XDG_STATE_HOME", str(root.parent / "state"))
    monkeypatch.setattr("isycode.workspace_trust.broad_workspace_reason",
                        lambda _path: "it is a mount point")
    with pytest.raises(ValueError):
        WorkspaceTrust().accept(authority, ACCEPT_PHRASE)
    assert not WorkspaceTrust().trusted(authority)


def test_untrusted_classic_still_asks_and_trust_is_not_a_tool(project):
    authority, root = project
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)
    preview = owner.preview("app.py", "x = 2\n")
    assert modal_required(authority, preview.request)
    assert owner.apply(preview, None).decision == "DENY"
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 1\n"
    banned = ("trust", "set_mode", "effect_ledger", "user_reset")
    assert not any(any(word in action_id for word in banned) for action_id in ACTION_BY_ID)
    source = Path(__file__).resolve().parents[1].joinpath("src", "isycode", "tui.py").read_text(
        encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: ast.get_source_segment(source, node) for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    writers = [name for name, body in methods.items() if "trust.accept(" in body]
    assert writers == ["_offer_quiet_trust"]
    assert "CommitApprovalScreen" in methods["_git_tool"]
    assert "_request_is_quiet" not in methods["_git_tool"]
    assert "no unsandboxed fallback" in methods["_run_workspace_command"]


def test_ordinary_flow_has_zero_per_action_approvals(project, tmp_path, monkeypatch):
    authority, root = project
    assert not quiet_classic(authority, ActionRequest(
        "workspace.files.write", root, str(root / "app.py"), {}, execution_owner="workspace_write"))
    _trust(authority)
    approvals = ActionApprovalStore()
    issued = []
    real_issue = approvals.issue

    def spy(request, **kwargs):
        issued.append(request.action_id)
        return real_issue(request, **kwargs)

    approvals.issue = spy
    reader = LocalWorkspaceReadOwner(root, authority)
    requests = []
    for index in range(10):
        outcome = reader.execute("workspace.files.read", {"path": f"read{index}.txt"})
        assert outcome.decision == "ALLOW"
        assert f"value {index}" in outcome.text
    writer = WorkspaceWriteOwner(root, authority, approvals)
    for index in range(5):
        preview = writer.preview("app.py", f"x = {index}\n")
        requests.append(preview.request)
        assert writer.apply(preview, None).decision == "ALLOW"
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 4\n"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "bwrap"
    fake.write_text(FAKE_BWRAP.format(python=Path(sys.executable).resolve()), encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_BWRAP_LOG", str(tmp_path / "bwrap.json"))
    runner = CommandRunOwner(root, authority, approvals)
    for index in range(3):
        preview = runner.prepare(["echo", f"test-{index}"])
        requests.append(preview.request)
        result = asyncio.run(runner.run(preview, None))
        assert result.decision == "ALLOW"
        assert f"test-{index}" in json.loads(result.text)["output"]
    assert issued == []
    assert not any(modal_required(authority, request) for request in requests)


def test_budget_scope_secrets_authority_and_missing_sandbox_stay_gated(project, monkeypatch):
    authority, root = project
    _trust(authority)
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)
    monkeypatch.setattr("isycode.effect_ledger.MAX_CHURN_PER_OPERATION", 4)
    preview = owner.preview("app.py", "x = 2\n")
    denied = owner.apply(preview, None)
    assert denied.decision == "DENY"
    assert "paths" in denied.reason and "deletes" in denied.reason and "churn" in denied.reason
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 1\n"
    monkeypatch.setattr("isycode.effect_ledger.MAX_CHURN_PER_OPERATION", 32 * 1024 * 1024)

    outside = reader_deny = LocalWorkspaceReadOwner(root, authority)
    assert outside.execute("workspace.files.read", {"path": "../outside"}).decision == "DENY"
    (root / ".env").write_text("TOKEN=1\n", encoding="utf-8")
    assert reader_deny.execute("workspace.files.read", {"path": ".env"}).decision == "DENY"
    secret = ActionRequest("workspace.files.read_sensitive", root, str(root / ".env"),
                           {"path": ".env"}, execution_owner="workspace_read")
    assert not authority.evaluate(secret, approvals=approvals, approval=approvals.issue(secret)).allowed
    commit = ActionRequest("git.commit", root, str(root), {"message": "x"}, execution_owner="git")
    assert modal_required(authority, commit)
    assert not authority.evaluate(commit, approvals=approvals, approval=None).allowed
    credential = ActionRequest("credentials.add", root, "openai", {"service": "openai"},
                               execution_owner="credential_add")
    assert not quiet_classic(authority, credential)
    assert not authority.evaluate(credential, approvals=approvals, approval=None).allowed

    authority.set_grant("workspace.files.write", enabled=False)
    again = owner.preview("app.py", "x = 9\n")
    assert owner.apply(again, None).decision == "DENY"
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 1\n"

    monkeypatch.setattr("isycode.command_runner.sandbox_executable", lambda: None)
    with pytest.raises(ValueError, match="no unsandboxed fallback"):
        CommandRunOwner(root, authority, approvals).prepare(["echo", "nope"])
    command = ActionRequest("workspace.command.run", root, "echo", {"argv": ["echo", "nope"]},
                            execution_owner="workspace_command")
    assert not quiet_classic(authority, command)
    assert modal_required(authority, command)
    restored = owner.preview("app.py", "x = 3\n")
    assert not modal_required(authority, restored.request)
    assert owner.apply(restored, None).decision == "DENY"
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    restored = owner.preview("app.py", "x = 3\n")
    assert owner.apply(restored, None).decision == "ALLOW"
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 3\n"


def test_security_has_no_effects_and_revocation_is_immediate(project):
    authority, root = project
    _trust(authority)
    names = [item["function"]["name"] for item in available_tools(root, authority)]
    assert names
    assert not any(token in name for name in names for token in ("write", "edit", "command", "commit"))
    authority.set_mode("security")
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)
    preview = owner.preview("app.py", "x = 8\n")
    assert owner.apply(preview, None).decision == "DENY"
    assert LocalWorkspaceReadOwner(root, authority).execute(
        "workspace.files.read", {"path": "app.py"}).decision == "DENY"
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 1\n"
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    assert LocalWorkspaceReadOwner(root, authority).execute(
        "workspace.files.read", {"path": "app.py"}).decision == "ALLOW"
    assert owner.apply(owner.preview("app.py", "x = 8\n"), None).decision == "DENY"
    assert available_tools(root, authority) == []
    authority.set_mode("classic")
    assert WorkspaceTrust().trusted(authority)
    assert not WorkspaceTrust().needs_onboarding(authority)
    assert owner.apply(owner.preview("app.py", "x = 5\n"), None).decision == "ALLOW"


def test_reopen_keeps_trust_and_other_roots_do_not_inherit(project, tmp_path):
    authority, root = project
    trust = WorkspaceTrust()
    assert trust.needs_onboarding(authority)
    _trust(authority)
    assert trust.trusted(authority)
    assert not trust.needs_onboarding(authority)
    record = trust._path_for(root).read_bytes()

    imported = tmp_path / "imported"
    shutil.copytree(root, imported)
    imported_authority = WorkspaceAuthority(imported, state_directory=tmp_path / "state" / "authority-import")
    imported_authority.set_mode("classic")
    assert not trust.trusted(imported_authority)
    assert trust.needs_onboarding(imported_authority)

    moved = tmp_path / "moved"
    root.rename(moved)
    moved_authority = WorkspaceAuthority(moved, state_directory=tmp_path / "state" / "authority-moved")
    moved_authority.set_mode("classic")
    assert not trust.trusted(moved_authority)
    assert trust._path_for(root).read_bytes() == record

    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    replaced = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority-replaced")
    replaced.set_mode("classic")
    assert not trust.trusted(replaced)
    assert trust._path_for(root).read_bytes() == record

    data = json.loads(record.decode("utf-8"))
    data["policy_version"] = 99
    trust._path_for(moved).write_bytes(record)
    path = trust._path_for(moved)
    path.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(path, 0o600)
    assert not trust.trusted(moved_authority)
    assert json.loads(path.read_text(encoding="utf-8"))["policy_version"] == 99

    authority_back = WorkspaceAuthority(moved, state_directory=tmp_path / "state" / "authority-moved")
    authority_back.policy_path.write_bytes(b"{")
    assert not trust.trusted(authority_back)
    assert json.loads(path.read_text(encoding="utf-8"))["policy_version"] == 99


def test_a_linked_trust_file_is_not_rewritten_into_trust(project, tmp_path):
    authority, root = project
    trust = WorkspaceTrust()
    _trust(authority)
    path = trust._path_for(root)
    outside = tmp_path / "outside-record"
    outside.write_text("keep\n", encoding="utf-8")
    path.unlink()
    path.symlink_to(outside)
    assert not trust.trusted(authority)
    assert outside.read_text(encoding="utf-8") == "keep\n"
    _trust(authority)
    assert outside.read_text(encoding="utf-8") == "keep\n"
    assert path.is_file() and not path.is_symlink()
    assert trust.trusted(authority)


def test_escape_remembers_the_decline_and_a_later_yes_trusts(tmp_path, monkeypatch, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    from isycode.tui import TUIApp, TailscaleConfirmScreen
    from isycode.user_defaults import UserDefaultsStore

    UserDefaultsStore().update(new_workspace="recurring", new_workspace_mode="classic")

    async def once(keys):
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(8):
                await pilot.pause()
                if isinstance(app.screen, TailscaleConfirmScreen):
                    break
            else:
                raise AssertionError(type(app.screen).__name__)
            for key in keys:
                await pilot.press(key)
            await pilot.pause()
        return app

    with capsys.disabled():
        asyncio.run(once(["escape"]))
    authority = WorkspaceAuthority(project_dir.resolve())
    trust = WorkspaceTrust()
    assert trust.declined(authority) and not trust.trusted(authority)

    async def second():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            assert not isinstance(app.screen, TailscaleConfirmScreen)

    with capsys.disabled():
        asyncio.run(second())


def test_yes_on_the_trust_screen_records_trust(tmp_path, monkeypatch, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    from isycode.tui import TUIApp, TailscaleConfirmScreen
    from isycode.user_defaults import UserDefaultsStore

    UserDefaultsStore().update(new_workspace="recurring", new_workspace_mode="classic")

    async def accept():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(8):
                await pilot.pause()
                if isinstance(app.screen, TailscaleConfirmScreen):
                    break
            else:
                raise AssertionError(type(app.screen).__name__)
            await pilot.press("y")
            await pilot.pause()

    with capsys.disabled():
        asyncio.run(accept())
    authority = WorkspaceAuthority(project_dir.resolve())
    assert WorkspaceTrust().trusted(authority)
