"""The GUS turn boundary (ADR 0013, MK5c): only GUS's role, never a change to L0."""
import asyncio
import json
import os

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner
from isycode.gus_l0 import gus_turn, gus_turn_active, l0_change_refusal, l0_refusal, on_gus_branch
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_trust import quiet_gus, quiet_request
from isycode.workspace_write import WorkspaceWriteOwner



@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "isycode"
    for path in ("src/isycode/security.py", "src/isycode/tui.py", "AGENTS.md"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(f"# {path}\n", encoding="utf-8")
    (root / ".isyroot").write_text("", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/gus/fix-something\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("classic")
    return root.resolve(), authority, ActionApprovalStore()


def _request(root, action, **parameters):
    return ActionRequest(action, root, str(root), parameters, execution_owner="workspace_write")


def test_outside_a_gus_turn_nothing_changes(repo):
    root, *_ = repo
    assert not gus_turn_active(root)
    assert l0_refusal(_request(root, "workspace.files.write", path="src/isycode/security.py")) is None
    assert l0_refusal(_request(root, "git.push")) is None
    assert l0_change_refusal(root, [{"path": "AGENTS.md", "kind": "modify"}]) is None


@pytest.mark.parametrize("action, parameters", [
    ("workspace.files.write", {"path": "src/isycode/security.py"}),
    ("workspace.files.write", {"path": "SRC/ISYCODE/SECURITY.PY"}),
    ("workspace.files.delete", {"path": "AGENTS.md"}),
    ("workspace.files.delete", {"path": "src/isycode"}),                 # a folder holding L0
    ("workspace.files.move", {"path": "src/isycode/tui.py", "to": "src/isycode/security.py"}),
    ("workspace.files.move", {"path": "docs/decisions/0013-gus-l1-l0.md", "to": "notes.md"}),
    ("workspace.files.restore", {"path": ".github/workflows/ci.yml"}),
    ("git.commit", {"paths": ("src/isycode/tui.py", "pyproject.toml")}),
])
def test_a_gus_turn_never_changes_l0(repo, action, parameters):
    root, *_ = repo
    with gus_turn(root):
        reason = l0_refusal(_request(root, action, **parameters))
    assert reason and "L0" in reason


@pytest.mark.parametrize("action", ["git.push", "git.branch.create", "credentials.use",
                                    "workspace.config.write", "mcp.invoke", "web.fetch"])
def test_a_gus_turn_stays_inside_the_role(repo, action):
    root, *_ = repo
    with gus_turn(root):
        assert "outside GUS's role" in l0_refusal(_request(root, action))


@pytest.mark.parametrize("action, parameters", [
    ("workspace.files.read", {"path": "src/isycode/security.py"}),      # GUS must know L0
    ("workspace.files.write", {"path": "src/isycode/tui.py"}),
    ("workspace.files.move", {"path": "src/isycode/tui.py", "to": "src/isycode/tui_old.py"}),
    ("git.commit", {"paths": ("src/isycode/tui.py",)}),
    ("workspace.turn.undo", {"paths": ("src/isycode/security.py",)}),     # undo only restores
])
def test_reading_l0_and_changing_l1_are_allowed(repo, action, parameters):
    root, *_ = repo
    with gus_turn(root):
        assert l0_refusal(_request(root, action, **parameters)) is None


def test_the_turn_belongs_to_one_workspace_and_to_tasks_started_inside_it(repo, tmp_path):
    root, *_ = repo
    other = tmp_path / "other"
    other.mkdir()
    seen = []

    async def later():
        await asyncio.sleep(0)
        seen.append(gus_turn_active(root))

    async def scenario():
        with gus_turn(root):
            assert not gus_turn_active(other)
            task = asyncio.ensure_future(later())        # started inside the turn
        outside = asyncio.ensure_future(later())         # started after it
        await asyncio.gather(task, outside)

    asyncio.run(scenario())
    assert seen == [True, False]
    assert not gus_turn_active(root)


def test_the_write_owner_refuses_l0_and_writes_l1_in_a_gus_turn(repo):
    root, authority, approvals = repo
    owner = WorkspaceWriteOwner(root, authority, approvals)
    with gus_turn(root):
        preview = owner.preview("src/isycode/security.py", "# weakened\n")
        outcome = owner.apply(preview, approvals.issue(preview.request))
        assert outcome.decision != "ALLOW" and "L0" in outcome.reason
        preview = owner.preview("src/isycode/tui.py", "# an L1 change\n")
        assert owner.apply(preview, approvals.issue(preview.request)).decision == "ALLOW"
    assert "weakened" not in (root / "src/isycode/security.py").read_text(encoding="utf-8")
    assert (root / "src/isycode/tui.py").read_text(encoding="utf-8") == "# an L1 change\n"


def test_gus_works_quietly_only_in_its_turn_on_its_branch_in_classic_or_flow(repo):
    root, authority, _ = repo
    request = _request(root, "workspace.files.write", path="src/isycode/tui.py")
    assert not quiet_request(authority, request)              # untrusted Classic asks
    with gus_turn(root):
        assert on_gus_branch(root) and quiet_gus(authority, request)
        assert not quiet_gus(authority, _request(root, "git.commit", paths=("x",)))
        (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        assert not quiet_gus(authority, request)              # off its branch it asks
        (root / ".git" / "HEAD").write_text("ref: refs/heads/gus/fix-something\n", encoding="utf-8")
        authority.set_mode("security")
        assert not quiet_gus(authority, request)              # Security never runs quietly
        authority.set_mode("flow")
        assert quiet_gus(authority, request)


@pytest.mark.parametrize("head", ["ref: refs/heads/gus/", "ref: refs/heads/gus/UPPER",
                                  "ref: refs/heads/gus/../main", "0123456789abcdef", ""])
def test_only_a_real_gus_branch_counts(repo, head):
    root, *_ = repo
    (root / ".git" / "HEAD").write_text(head + "\n", encoding="utf-8")
    assert not on_gus_branch(root)


def test_command_promotion_refuses_l0_changes_in_a_gus_turn(repo):
    """GK5-01: the staging promotion is checked too, not only workspace.files.write."""
    root, authority, approvals = repo
    owner = CommandRunOwner(root, authority, approvals)
    changes = [{"path": "src/isycode/tui.py", "kind": "modify"},
               {"path": "src/isycode/security.py", "kind": "modify"}]
    assert owner._revoked_effect(changes) is None
    with gus_turn(root):
        assert "L0" in owner._revoked_effect(changes)
        assert owner._revoked_effect(changes[:1]) is None
        assert "L0" in owner._revoked_effect([{"path": "docs/decisions/x.md", "kind": "add"}])


@pytest.mark.skipif(os.name != "posix", reason="the command sandbox is POSIX only")
def test_a_real_command_in_a_gus_turn_cannot_promote_an_l0_change(tmp_path, monkeypatch):
    """GK5-01 with a real command: L1 and L0 changed in staging; nothing is promoted."""
    from test_command_runner import _run, sandbox as make_sandbox
    owner, authority, approvals, _fake, _log = make_sandbox.__wrapped__(tmp_path, monkeypatch)
    authority.set_mode("classic")
    (owner.root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    script = "open('src/app.py','w').write('l1\\n'); open('AGENTS.md','w').write('gone\\n')"
    with gus_turn(owner.root):
        _, outcome = _run(owner, approvals, ["python3", "-c", script])
    staging = json.loads(outcome.text)["staging"]
    assert staging["promotion"]["state"] == "denied" and "L0" in staging["promotion"]["reason"]
    assert (owner.root / "AGENTS.md").read_text(encoding="utf-8") == "rules\n"
    assert (owner.root / "src" / "app.py").read_text(encoding="utf-8") == "print('app')\n"
