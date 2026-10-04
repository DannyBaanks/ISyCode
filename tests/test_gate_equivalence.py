"""G1-01 and G1-02: one decision for the same effect, and no effect after revocation."""
import ast
import json
from io import StringIO
from pathlib import Path

from isycode.action_runtime import LocalWorkspaceReadOwner, ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.decision_view import denied_line, verified_receipt_line
from isycode.headless import _dispatch
from isycode.security import (
    ActionRequest, AuthorityDecision, IsySentinel, SystembilityResult,
)
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner
from isycode.effect_policy import implicit_actions


def _workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    return authority, root.resolve()


def _read_request(owner: LocalWorkspaceReadOwner, root: Path) -> ActionRequest:
    target = str(owner._lexical_target("app.py"))
    return ActionRequest("workspace.files.read", root, target, {"path": "app.py"},
                         execution_owner="workspace_read")


def test_the_same_read_has_one_decision_in_the_owner_the_gate_and_headless(tmp_path, monkeypatch):
    authority, root = _workspace(tmp_path, monkeypatch)
    authority.set_mode("classic")
    owner = LocalWorkspaceReadOwner(root, authority)
    request = _read_request(owner, root)
    direct = owner.execute("workspace.files.read", {"path": "app.py"})
    _, decision = owner.gate.authorize(request)
    log = StringIO()
    _dispatch(root, authority, {
        "id": "call-1",
        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "app.py"})},
    }, log)
    assert direct.decision == "ALLOW"
    assert decision.allowed is True
    assert "EffectClass" not in {item.name for item in decision.checks}
    assert "ALLOW" in log.getvalue()
    assert (root / "app.py").read_text() == "x = 1\n"

    authority.set_mode("security")
    denied = owner.execute("workspace.files.read", {"path": "app.py"})
    _, denied_decision = owner.gate.authorize(request)
    denied_log = StringIO()
    _dispatch(root, authority, {
        "id": "call-2",
        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "app.py"})},
    }, denied_log)
    assert denied.decision == "DENY"
    assert denied_decision.allowed is False
    assert "DENY" in denied_log.getvalue()
    assert (root / "app.py").read_text() == "x = 1\n"


def test_unknown_owner_empty_checks_and_exceptions_deny(tmp_path, monkeypatch):
    authority, root = _workspace(tmp_path, monkeypatch)
    authority.set_mode("classic")
    owner = LocalWorkspaceReadOwner(root, authority)
    request = _read_request(owner, root)
    unknown = ProductActionGate(root, authority, owner_id="not_registered")
    foreign = ActionRequest(request.action_id, root, request.target, dict(request.parameters),
                            execution_owner="not_registered")
    assert unknown.authorize(foreign)[1].allowed is False
    assert (root / "app.py").read_text() == "x = 1\n"

    grant = AuthorityDecision(True, "grant:test", "fixture", request.digest)
    empty = IsySentinel(()).evaluate(request, grant)
    assert empty.allowed is False
    assert any(item.name == "SystembilitySet" and item.passed is False for item in empty.checks)

    class Exploding:
        name = "Exploding"

        def evaluate(self, request, authority):
            raise RuntimeError("secret detail")

    exploded = IsySentinel((Exploding(),)).evaluate(request, grant)
    assert exploded.allowed is False
    failed = next(item for item in exploded.checks if item.name == "Exploding")
    assert failed.passed is False
    assert failed.reason == "Systembility evaluation failed"
    assert "secret detail" not in repr(exploded)


def test_unclassified_action_denies_before_an_effect(tmp_path, monkeypatch):
    authority, root = _workspace(tmp_path, monkeypatch)
    authority.set_mode("classic")
    gate = ProductActionGate(root, authority, owner_id="workspace_read")
    request = ActionRequest("not.registered", root, str(root / "app.py"), {"path": "app.py"},
                            execution_owner="workspace_read")
    authority_decision, decision = gate.authorize(request)
    assert authority_decision.allowed is False
    assert decision.allowed is False
    assert [item.name for item in decision.checks] == ["EffectClass"]
    assert (root / "app.py").read_text() == "x = 1\n"


def test_explicit_denial_beats_the_classic_preset(tmp_path, monkeypatch):
    authority, root = _workspace(tmp_path, monkeypatch)
    authority.set_mode("classic")
    assert "workspace.files.read" in implicit_actions("classic")
    authority.set_grant("workspace.files.read", enabled=False)
    outcome = LocalWorkspaceReadOwner(root, authority).execute(
        "workspace.files.read", {"path": "app.py"})
    assert outcome.decision == "DENY"
    assert "revoked" in outcome.reason
    assert (root / "app.py").read_text() == "x = 1\n"


def test_revocation_changed_digest_expiry_reuse_and_other_workspace_write_nothing(
        tmp_path, monkeypatch):
    authority, root = _workspace(tmp_path, monkeypatch)
    authority.set_mode("classic")
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)
    original = (root / "app.py").read_text()

    revoked = owner.preview("app.py", "x = 2\n")
    authority.set_grant("workspace.files.write", enabled=False)
    assert owner.apply(revoked, approvals.issue(revoked.request)).decision == "DENY"
    assert (root / "app.py").read_text() == original
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])

    changed = owner.preview("app.py", "x = 3\n")
    (root / "app.py").write_text("human\n", encoding="utf-8")
    assert owner.apply(changed, approvals.issue(changed.request)).decision == "DENY"
    assert (root / "app.py").read_text() == "human\n"
    (root / "app.py").write_text(original, encoding="utf-8")

    clock = {"now": 1_000.0}
    monkeypatch.setattr("isycode.approvals.time.monotonic", lambda: clock["now"])
    expiring = owner.preview("app.py", "x = 4\n")
    approval = approvals.issue(expiring.request, ttl_seconds=1)
    clock["now"] = 1_002.0
    assert owner.apply(expiring, approval).decision == "DENY"
    assert (root / "app.py").read_text() == original

    clock["now"] = 2_000.0
    reused = owner.preview("app.py", "x = 5\n")
    token = approvals.issue(reused.request)
    assert owner.apply(reused, token).decision == "ALLOW"
    assert owner.apply(reused, token).decision == "DENY"
    assert (root / "app.py").read_text() == "x = 5\n"

    other = tmp_path / "other"
    other.mkdir()
    (other / "app.py").write_text("keep\n", encoding="utf-8")
    foreign = ActionRequest(
        "workspace.files.write", other, str(other / "app.py"),
        {"path": "app.py", "before_sha256": "absent", "after_sha256": "a" * 64,
         "size": 1, "diff_sha256": "b" * 64},
        execution_owner="workspace_write")
    gate = ProductActionGate(root, authority, owner_id="workspace_write")
    assert gate.authorize(foreign, approvals=approvals,
                          approval=approvals.issue(foreign))[1].allowed is False
    assert (other / "app.py").read_text() == "keep\n"
    assert (root / "app.py").read_text() == "x = 5\n"


def test_receipt_text_is_presentation_and_imports_no_policy():
    line = verified_receipt_line("rcpt_" + "ab" * 8)
    assert line == "ISySentinel ALLOW · local receipt rcpt_abababa verified"
    assert verified_receipt_line("rcpt_" + "ab" * 8, local=False) == (
        "ISySentinel ALLOW · receipt rcpt_abababa verified")
    assert denied_line("  fresh   request-bound approval is required  ").startswith(
        "ISySentinel DENY ·")
    assert "ALLOW" not in denied_line("denied")

    root = Path(__file__).resolve().parents[1]
    forbidden = {
        "isycode.workspace_authority", "isycode.security", "isycode.approvals",
        "isycode.action_runtime", "isycode.command_runner", "isycode.effect_policy",
    }

    def imported(path: Path) -> set[str]:
        found: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    view = root / "src" / "isycode" / "decision_view.py"
    package = root / "src" / "isycode"
    tui = package / "tui.py"
    surfaces = [tui, *sorted(package.glob("tui_*.py"))]
    assert imported(view).isdisjoint(forbidden)
    tui_imports = set().union(*(imported(path) for path in surfaces))
    assert "isycode.decision_view" in tui_imports
    assert "isycode.effect_policy" not in tui_imports
    joined = "\n".join(path.read_text(encoding="utf-8") for path in surfaces)
    assert "verified_receipt_line(" in joined
    assert "_workspace_read_owner().execute" in joined

