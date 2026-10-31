"""Per-command staging budgets stay finite, reviewed, and sandboxed."""
import asyncio
import json
import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from textual.app import App
from textual.containers import VerticalScroll
from textual.widgets import Button

from isycode import action_runtime, command_runner, staging
from isycode.approvals import ActionApprovalStore
from isycode.workspace_trust import (
    ACCEPT_PHRASE, WorkspaceTrust, modal_required, quiet_classic,
)
from sandbox_gate import requires_sandbox, sandbox_missing
from test_command_runner import sandbox
from test_command_runner_tui import _preview


DEFAULT = 512 * 1024**2
MAXIMUM = 8 * 1024**3
INVALID_BUDGETS = [None, True, False, 0, -1, 1.0, "32", [], {},
                   float("inf"), float("nan"), MAXIMUM + 1]


@pytest.fixture
def trusted_sandbox(sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "isycode-state"))
    authority = sandbox[1]
    authority.set_mode("classic")
    WorkspaceTrust().accept(authority, ACCEPT_PHRASE)
    assert WorkspaceTrust().trusted(authority)
    return sandbox


def test_command_budget_constants_and_tool_proposal_contract():
    assert action_runtime.COMMAND_DEFAULT_STAGE_BYTES == DEFAULT
    assert action_runtime.COMMAND_MAX_STAGE_BYTES == MAXIMUM
    schema = command_runner.COMMAND_TOOL["function"]["parameters"]
    budget = schema["properties"]["max_stage_bytes"]
    assert budget["type"] == "integer"
    assert budget["minimum"] == 1 and budget["maximum"] == MAXIMUM
    assert "max_stage_bytes" not in schema["required"]
    assert schema["additionalProperties"] is False
    description = budget["description"].lower()
    assert "propos" in description and "approv" in description


@pytest.mark.parametrize("kwargs", [{}, {"max_stage_bytes": None}])
def test_staging_default_refuses_but_explicit_larger_cap_copies(tmp_path, monkeypatch, kwargs):
    root = tmp_path / "project"
    root.mkdir()
    original = root / "data.bin"
    original.write_bytes(b"0123456789")
    monkeypatch.setattr(staging, "MAX_STAGE_BYTES", 8)
    with pytest.raises(staging.StagingError, match="budget"):
        staging.prepare_staging(root, **kwargs)

    prepared = staging.prepare_staging(root, max_stage_bytes=10)
    try:
        assert prepared.root != root and root not in prepared.root.parents
        assert (prepared.root / "data.bin").read_bytes() == original.read_bytes()
        (prepared.root / "data.bin").write_bytes(b"isolated")
        assert original.read_bytes() == b"0123456789"
    finally:
        staging.cleanup_staging(prepared)
    assert not prepared.root.exists()


@pytest.mark.parametrize("budget", [value for value in INVALID_BUDGETS if value is not None])
def test_staging_rejects_invalid_explicit_caps_before_allocating(tmp_path, monkeypatch, budget):
    root = tmp_path / "project"
    root.mkdir()
    allocate = Mock(side_effect=AssertionError("invalid budget allocated staging"))
    monkeypatch.setattr(staging.tempfile, "mkdtemp", allocate)
    with pytest.raises((ValueError, staging.StagingError)):
        staging.prepare_staging(root, max_stage_bytes=budget)
    allocate.assert_not_called()


@pytest.mark.parametrize("free_delta", [-1, 0])
def test_disk_check_measures_the_entire_tree_beyond_the_old_cap(tmp_path, monkeypatch, free_delta):
    root = tmp_path / "project"
    root.mkdir()
    for name in ("a.bin", "b.bin", "c.bin"):
        (root / name).write_bytes(b"x" * 9)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(staging, "MAX_STAGE_BYTES", 8)
    monkeypatch.setattr(staging.tempfile, "tempdir", str(scratch))
    monkeypatch.setattr(staging.shutil, "disk_usage", lambda _path: SimpleNamespace(
        free=staging.FREE_MARGIN_BYTES + 2 * 27 + free_delta))

    if free_delta < 0:
        with pytest.raises(staging.StagingError, match="free space"):
            staging.prepare_staging(root, max_stage_bytes=32)
    else:
        prepared = staging.prepare_staging(root, max_stage_bytes=32)
        try:
            assert sum(path.stat().st_size for path in prepared.root.iterdir()) == 27
            assert staging.measure_changes(prepared) == []
        finally:
            staging.cleanup_staging(prepared)
    assert list(scratch.iterdir()) == []
    assert all(path.read_bytes() == b"x" * 9 for path in root.iterdir())


def test_source_growth_during_copy_refuses_and_cleans_partial_staging(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    original = root / "growing.bin"
    original.write_bytes(b"x" * 8)
    (root / "stable.bin").write_bytes(b"safe")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(staging.tempfile, "tempdir", str(scratch))
    copy_tree = staging._copy_tree
    copied_to = []
    copied_bytes = []

    def grow_then_copy(source, destination, *args, **kwargs):
        copied_to.append(destination)
        original.write_bytes(b"x" * 33)
        try:
            return copy_tree(source, destination, *args, **kwargs)
        finally:
            copied_bytes.append(sum(path.stat().st_size for path in destination.rglob("*")
                                    if path.is_file()))

    monkeypatch.setattr(staging, "_copy_tree", grow_then_copy)
    with pytest.raises(staging.StagingError):
        staging.prepare_staging(root, max_stage_bytes=32)
    assert copied_to, "the source must grow after measurement, when copying starts"
    assert max(copied_bytes) <= 32
    assert list(scratch.iterdir()) == []
    assert original.read_bytes() == b"x" * 33
    assert (root / "stable.bin").read_bytes() == b"safe"


def test_explicit_cap_still_applies_only_to_the_selected_scope(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_bytes(b"app")
    (root / "sibling.bin").write_bytes(b"x" * 64)
    monkeypatch.setattr(staging, "MAX_STAGE_BYTES", 1)
    prepared = staging.prepare_staging(root, scope="src", max_stage_bytes=3)
    try:
        assert prepared.scope == "src"
        assert (prepared.root / "src" / "app.py").read_bytes() == b"app"
        assert not (prepared.root / "sibling.bin").exists()
    finally:
        staging.cleanup_staging(prepared)
    assert (root / "sibling.bin").read_bytes() == b"x" * 64


@requires_sandbox
class TestCommandBudget:
    def test_default_preview_omits_optional_budget_and_preserves_request_digest(self, sandbox):
        owner = sandbox[0]
        implicit = owner.prepare(["echo", "ok"])
        explicit = owner.prepare(["echo", "ok"], max_stage_bytes=DEFAULT)
        assert implicit.max_stage_bytes == explicit.max_stage_bytes == DEFAULT
        assert "max_stage_bytes" not in implicit.request.parameters
        assert implicit == explicit and implicit.request.digest == explicit.request.digest

    @pytest.mark.parametrize("budget", [1, DEFAULT - 1, DEFAULT + 1, MAXIMUM])
    def test_nondefault_preview_binds_the_exact_cap(self, sandbox, budget):
        owner = sandbox[0]
        preview = owner.prepare(["echo", "ok"], max_stage_bytes=budget)
        assert preview.max_stage_bytes == budget
        assert preview.request.parameters["max_stage_bytes"] == budget
        ordinary = owner.prepare(["echo", "ok"])
        assert preview.request.digest != ordinary.request.digest
        assert {key: value for key, value in preview.request.parameters.items()
                if key != "max_stage_bytes"} == dict(ordinary.request.parameters)

    @pytest.mark.parametrize("budget", INVALID_BUDGETS)
    def test_prepare_refuses_invalid_caps(self, sandbox, budget):
        with pytest.raises(ValueError, match="stag|budget"):
            sandbox[0].prepare(["echo", "ok"], max_stage_bytes=budget)

    @pytest.mark.parametrize("budget", [None, True, False, 0, -1, 1.0, "32", [], {}, MAXIMUM + 1])
    def test_sentinel_refuses_forged_budget_even_with_a_bound_approval(self, sandbox, budget):
        owner, authority, approvals, fake, log = sandbox
        authority.set_grant("workspace.command.run", enabled=True, executables=[fake])
        preview = owner.prepare(["echo", "ok"])
        request = replace(preview.request, parameters={
            **dict(preview.request.parameters), "max_stage_bytes": budget})
        _, decision = owner.gate.authorize(
            request, approvals=approvals, approval=approvals.issue(request))
        assert not decision.allowed
        boundary = next(check for check in decision.checks if check.name == "CommandProcessBoundary")
        assert not boundary.passed
        assert not log.exists()

    def test_windows_refuses_expansion_without_changing_the_posix_sandbox(self, sandbox, monkeypatch):
        windows_os = SimpleNamespace(**{**vars(os), "name": "nt"})
        monkeypatch.setattr(command_runner, "os", windows_os)
        monkeypatch.setattr(action_runtime, "os", windows_os)
        owner = sandbox[0]
        assert owner.prepare(["echo", "ok"], max_stage_bytes=DEFAULT).max_stage_bytes == DEFAULT
        with pytest.raises(ValueError, match="Windows|[Ww]indows|stag|budget"):
            owner.prepare(["echo", "ok"], max_stage_bytes=DEFAULT + 1)

    def test_trusted_classic_is_quiet_only_at_the_ordinary_cap(self, trusted_sandbox):
        owner, authority, _, _, _ = trusted_sandbox
        ordinary = owner.prepare(["echo", "ordinary"])
        assert quiet_classic(authority, ordinary.request)
        assert not modal_required(authority, ordinary.request)
        assert asyncio.run(owner.run(ordinary, None)).decision == "ALLOW"
        expanded = owner.prepare(["echo", "expanded"], max_stage_bytes=DEFAULT + 1)
        assert not quiet_classic(authority, expanded.request)
        assert modal_required(authority, expanded.request)

    def test_trusted_classic_tool_expansion_still_opens_review(self, trusted_sandbox, monkeypatch):
        from isycode import tui_app_workspace
        from isycode.tui import CommandApprovalScreen

        owner, authority, approvals, _, log = trusted_sandbox
        monkeypatch.setattr(tui_app_workspace, "CommandRunOwner", lambda *args: owner)
        monkeypatch.setattr(tui_app_workspace, "WorkspaceAuthority", lambda _root: authority)
        reviewed = []

        async def reject(screen):
            assert isinstance(screen, CommandApprovalScreen)
            reviewed.append(screen.preview.max_stage_bytes)
            return False

        host = SimpleNamespace(
            _workspace_root=owner.root, _action_approvals=approvals,
            _command_tool_enabled=lambda: True,
            _request_is_quiet=lambda request: quiet_classic(authority, request),
            _append=lambda *args: None, _await_screen=reject,
            notify_semantic=lambda *args, **kwargs: None)
        response = asyncio.run(tui_app_workspace.WorkspaceMixin._run_workspace_command(
            host, {"argv": ["echo", "expanded"], "max_stage_bytes": DEFAULT + 1}))
        assert json.loads(response)["status"] == "rejected_by_user"
        assert reviewed == [DEFAULT + 1] and not log.exists()

    @pytest.mark.parametrize("kind", ["missing", "delegated", "expired", "other-budget", "forged-user"])
    def test_expanded_cap_needs_a_valid_exact_user_approval(
            self, trusted_sandbox, monkeypatch, kind):
        owner, _, approvals, _, log = trusted_sandbox
        preview = owner.prepare(["echo", "expanded"], max_stage_bytes=DEFAULT + 1)
        if kind == "missing":
            approval = None
        elif kind in {"delegated", "forged-user"}:
            approval = approvals.issue(preview.request, mode="delegated")
            if kind == "forged-user":
                approval = replace(approval, mode="user")
        elif kind == "other-budget":
            other = owner.prepare(["echo", "expanded"], max_stage_bytes=DEFAULT + 2)
            approval = approvals.issue(other.request)
        else:
            from isycode import approvals as approval_module
            approval = approvals.issue(preview.request)
            monkeypatch.setattr(approval_module, "time", SimpleNamespace(
                monotonic=lambda: approval.expires_at + 1))
        allocate = Mock(side_effect=AssertionError("unapproved budget allocated staging"))
        monkeypatch.setattr(command_runner, "prepare_staging", allocate)
        outcome = asyncio.run(owner.run(preview, approval))
        assert outcome.decision == "DENY", outcome.reason
        assert outcome.receipt is None
        allocate.assert_not_called()
        assert not log.exists()

    def test_reviewed_expansion_is_forwarded_once_and_cannot_be_replayed(
            self, trusted_sandbox, monkeypatch):
        owner, _, approvals, _, log = trusted_sandbox
        prepare = Mock(wraps=command_runner.prepare_staging)
        monkeypatch.setattr(command_runner, "prepare_staging", prepare)
        preview = owner.prepare(["echo", "expanded"], max_stage_bytes=DEFAULT + 1)
        approval = approvals.issue(preview.request, mode="user")
        outcome = asyncio.run(owner.run(preview, approval))
        assert outcome.decision == "ALLOW", outcome.reason
        assert outcome.receipt.verify(preview.request, outcome.text)
        assert json.loads(outcome.text)["output"] == "expanded\n"
        prepare.assert_called_once_with(owner.root, scope=".", max_stage_bytes=DEFAULT + 1)
        evidence = log.read_bytes()
        replay = asyncio.run(owner.run(preview, approval))
        assert replay.decision == "DENY" and replay.receipt is None
        assert prepare.call_count == 1 and log.read_bytes() == evidence

    def test_expansion_never_replaces_the_executable_grant(self, sandbox):
        owner, _, approvals, _, log = sandbox
        preview = owner.prepare(["echo", "no-grant"], max_stage_bytes=DEFAULT + 1)
        outcome = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
        assert outcome.decision == "DENY" and "grant" in outcome.reason
        assert not log.exists()

    def test_owner_enforces_a_small_reviewed_cap_before_starting(self, sandbox):
        owner, authority, approvals, fake, log = sandbox
        authority.set_grant("workspace.command.run", enabled=True, executables=[fake])
        refused = owner.prepare(["echo", "bounded"], max_stage_bytes=1)
        outcome = asyncio.run(owner.run(refused, approvals.issue(refused.request)))
        assert outcome.decision == "ERROR" and "budget" in outcome.reason
        assert outcome.receipt is None and not log.exists()
        allowed = owner.prepare(["echo", "bounded"], max_stage_bytes=64)
        outcome = asyncio.run(owner.run(allowed, approvals.issue(allowed.request)))
        assert outcome.decision == "ALLOW", outcome.reason
        assert json.loads(outcome.text)["output"] == "bounded\n"

    def test_expanded_copy_keeps_masks_readonly_marker_and_network_denial(self, trusted_sandbox):
        owner, _, approvals, _, log = trusted_sandbox
        (owner.root / ".env").write_text("TOKEN=synthetic\n", encoding="utf-8")
        (owner.root / ".git").mkdir()
        preview = owner.prepare(["python3", "-c",
                                 "import json,resource,socket; "
                                 "print(json.dumps(resource.getrlimit(resource.RLIMIT_FSIZE)),flush=True); "
                                 "socket.socket()"],
                                max_stage_bytes=DEFAULT + 1)
        assert preview.request.parameters["network"] == "denied"
        assert preview.request.parameters["max_output_bytes"] == action_runtime.COMMAND_MAX_OUTPUT_BYTES
        outcome = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
        assert outcome.decision == "ALLOW", outcome.reason
        result = json.loads(outcome.text)
        assert result["exit_code"] != 0 and "PermissionError" in result["output"]
        assert json.loads(result["output"].splitlines()[0]) == [DEFAULT, DEFAULT]
        logged = json.loads(log.read_text(encoding="utf-8"))
        assert sorted(logged["masks"]) == ["/workspace/.env", "/workspace/.git"]
        assert logged["readonly"] == ["/workspace/.isyroot"]
        assert "--unshare-all" in logged["options"] and "--share-net" not in logged["options"]
        assert "--clearenv" in logged["options"]
        assert (owner.root / ".env").read_text(encoding="utf-8") == "TOKEN=synthetic\n"


@pytest.mark.parametrize("supplied", [None, 32, DEFAULT + 1])
def test_tui_forwards_the_budget_proposal_and_rejection_never_runs(tmp_path, monkeypatch, supplied):
    from isycode import tui_app_workspace
    from isycode.tui import CommandApprovalScreen

    cap = DEFAULT if supplied is None else supplied
    preview = replace(_preview(tmp_path), max_stage_bytes=cap)
    owner = SimpleNamespace(prepare=Mock(return_value=preview), run=Mock())
    approvals = ActionApprovalStore()
    issue = Mock(wraps=approvals.issue)
    monkeypatch.setattr(approvals, "issue", issue)
    monkeypatch.setattr(tui_app_workspace, "CommandRunOwner", lambda *args: owner)
    monkeypatch.setattr(tui_app_workspace, "WorkspaceAuthority", lambda _root: None)
    reviewed = []

    async def reject(screen):
        assert isinstance(screen, CommandApprovalScreen)
        reviewed.append(screen.preview)
        return False

    host = SimpleNamespace(
        _workspace_root=tmp_path, _action_approvals=approvals,
        _command_tool_enabled=lambda: True, _request_is_quiet=lambda _request: False,
        _append=lambda *args: None, _await_screen=reject, notify_semantic=lambda *args, **kwargs: None)
    arguments = {"argv": ["echo", "hi there"]}
    if supplied is not None:
        arguments["max_stage_bytes"] = supplied
    response = asyncio.run(tui_app_workspace.WorkspaceMixin._run_workspace_command(host, arguments))
    assert json.loads(response)["status"] == "rejected_by_user"
    assert reviewed == [preview]
    assert owner.prepare.call_args.kwargs["max_stage_bytes"] == cap
    issue.assert_not_called()
    owner.run.assert_not_called()


@pytest.mark.parametrize("cap", [DEFAULT, 2 * DEFAULT])
@pytest.mark.parametrize("action", ["enter", "escape", "run"])
def test_budget_review_discloses_mib_and_keeps_reject_as_default(tmp_path, monkeypatch, cap, action):
    from isycode import localization
    from isycode.tui import CommandApprovalScreen, plain_text

    monkeypatch.setattr(localization, "_CATALOG", {})
    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(CommandApprovalScreen(replace(_preview(tmp_path), max_stage_bytes=cap)),
                             results.append)

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            text = plain_text(screen.query_one("#command-approval-budget")).lower().replace(",", "")
            assert str(cap // 1024**2) in text and "mib" in text
            if cap > DEFAULT:
                assert all(word in text for word in ("temporary", "disk", "time", "permission"))
                assert "not" in text or "unchanged" in text
            reject = screen.query_one("#command-approval-reject", Button)
            run = screen.query_one("#command-approval-run", Button)
            assert screen.focused is reject
            assert screen.region.contains_region(reject.region)
            assert screen.region.contains_region(run.region)
            assert not reject.region.overlaps(run.region)
            if action == "run":
                await pilot.click("#command-approval-run")
            else:
                await pilot.press(action)
            await pilot.pause()

    asyncio.run(scenario())
    assert results == [action == "run"]


def test_expanded_budget_review_scrolls_without_hiding_actions_at_80x24(tmp_path):
    from isycode.tui import CommandApprovalScreen

    preview = replace(_preview(tmp_path), max_stage_bytes=2 * DEFAULT,
                      argv=("echo", " ".join(f"argument-{index}" for index in range(200))))

    class Host(App):
        def on_mount(self):
            self.push_screen(CommandApprovalScreen(preview))

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            body = screen.query_one("#command-approval-body", VerticalScroll)
            assert body.max_scroll_y > 0
            # The default scroll is deferred until a refresh; make the assertion deterministic.
            body.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            assert body.scroll_y > 0
            for selector in ("#command-approval-reject", "#command-approval-run"):
                button = screen.query_one(selector, Button)
                assert button.region.height > 0
                assert screen.region.contains_region(button.region)
                assert not body.region.overlaps(button.region)
            await pilot.press("escape")

    asyncio.run(scenario())


@pytest.mark.skipif(sandbox_missing(), reason="the real bubblewrap check needs the host sandbox")
def test_reviewed_expansion_keeps_real_bubblewrap_isolation(tmp_path, monkeypatch):
    from test_staging import _bubblewrap_namespace_works, _owner

    if not _bubblewrap_namespace_works():
        pytest.skip("bubblewrap cannot create a namespace; no host fallback")
    owner, authority, approvals, root = _owner(tmp_path, monkeypatch)
    authority.set_grant("workspace.command.run", enabled=True,
                        executables=[command_runner.sandbox_executable()])
    (root / ".env").write_text("synthetic-secret\n", encoding="utf-8")
    script = (
        "from pathlib import Path; import socket\n"
        "try:\n    secret = Path('.env').read_text()\n"
        "except PermissionError:\n    secret = ''\n"
        "assert secret == ''\n"
        f"assert not Path({str(root)!r}).exists()\n"
        "Path('src/app.py').write_text('staged only\\n')\n"
        "print('isolated', flush=True); socket.socket()")
    preview = owner.prepare(["python3", "-c", script], max_stage_bytes=2 * DEFAULT)
    outcome = asyncio.run(owner.run_staged(preview, approvals.issue(preview.request)))
    assert outcome.decision == "ALLOW", outcome.reason
    result = json.loads(outcome.text)
    assert result["exit_code"] != 0 and "PermissionError" in result["output"]
    assert "isolated" in result["output"]
    assert "src/app.py" in result["staging"]["pending"]
    assert result["staging"]["promoted_count"] == 0
    assert (root / "src/app.py").read_text(encoding="utf-8") == "keep\n"
    assert (root / ".env").read_text(encoding="utf-8") == "synthetic-secret\n"


@pytest.mark.parametrize("locale, expected", [("es", "Presupuesto de copia temporal"),
                                              ("en", "Temporary input-copy budget"),
                                              ("zh", "临时输入复制预算")])
def test_budget_review_is_localized_at_80x24(tmp_path, monkeypatch, locale, expected):
    from isycode import localization
    from isycode.tui import CommandApprovalScreen, plain_text

    for name in ("_LOCALE", "_CATALOG", "_CATALOG_ROOT", "_DIAGNOSTIC"):
        monkeypatch.setattr(localization, name, getattr(localization, name))
    localization.configure_locale(locale)

    class Host(App):
        def on_mount(self):
            self.push_screen(CommandApprovalScreen(
                replace(_preview(tmp_path), max_stage_bytes=2 * DEFAULT)))

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert expected in plain_text(screen.query_one("#command-approval-budget"))
            assert screen.focused.id == "command-approval-reject"
            assert screen.region.contains_region(screen.query_one("#command-approval-run").region)
            await pilot.press("escape")
    asyncio.run(scenario())
