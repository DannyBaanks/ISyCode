"""GUS generations (ADR 0013, MK5d): V/T/A/L/S run by ISyCode, sealed or rejected with evidence."""
import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.action_runtime import ProductActionGate
from isycode.git_owner import GitOwner, git_executable
from isycode.gus_generation import (
    AUTHORITY_TESTS, LINT, PROBE, PYTEST, build_generation, seal, targeted_tests, validate)
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

CLEAN = {"base": "a" * 40, "head": "b" * 40, "clean": True, "truncated": False, "diff": "+x\n",
         "changes": [{"status": "M", "path": "src/isycode/work_list.py"},
                     {"status": "A", "path": "tests/test_work_list_extra.py"}]}
RECORDED = {"base": "a" * 40, "l0": "f" * 64}


def _git(root, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root.parent)}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True,
                          capture_output=True, text=True).stdout


def test_v_passes_only_for_a_clean_committed_l1_range_with_the_same_l0():
    assert validate(CLEAN, RECORDED, "f" * 64).status == "PASS"


@pytest.mark.parametrize("change, recorded, digest, reason", [
    ({"clean": False}, RECORDED, "f" * 64, "uncommitted"),
    ({"changes": []}, RECORDED, "f" * 64, "nothing was committed"),
    ({"truncated": True}, RECORDED, "f" * 64, "too large"),
    ({"changes": [{"status": "M", "path": "src/isycode/security.py"}]}, RECORDED, "f" * 64, "L0 paths"),
    ({"changes": [{"status": "R", "from": "AGENTS.md", "path": "notes.md"}]}, RECORDED, "f" * 64, "L0 paths"),
    ({}, RECORDED, "e" * 64, "fingerprint changed"),
    ({}, None, "f" * 64, "start is unknown"),
])
def test_v_refuses_dirty_empty_l0_or_unknown_ranges(change, recorded, digest, reason):
    result = validate({**CLEAN, **change}, recorded, digest)
    assert result.status == "FAIL" and reason in result.detail


def test_targeted_tests_are_the_changed_tests_and_those_of_changed_modules(tmp_path):
    (tmp_path / "tests").mkdir()
    for name in ("test_work_list.py", "test_work_list_tui.py", "test_other.py"):
        (tmp_path / "tests" / name).write_text("", encoding="utf-8")
    changes = [{"status": "M", "path": "src/isycode/work_list.py"},
               {"status": "M", "path": "tests/test_other.py"},
               {"status": "D", "path": "src/isycode/gone.py"},
               {"status": "M", "path": "docs/readme.md"}]
    assert targeted_tests(tmp_path, changes) == [
        "tests/test_other.py", "tests/test_work_list.py", "tests/test_work_list_tui.py"]


def _runner(results, calls):
    async def run(argv):
        calls.append(argv)
        for prefix, outcome in results:
            if argv[:len(prefix)] == prefix:
                return outcome
        return 0, "ok"
    return run


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_work_list.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "isycode").mkdir(parents=True)
    (tmp_path / "src" / "isycode" / "work_list.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_all_gates_passing_seals_a_reproducible_generation(tree):
    calls = []
    record = asyncio.run(build_generation(tree, "gus/x", CLEAN, RECORDED, "f" * 64, _runner([], calls)))
    assert record["state"] == "SEALED"
    assert record["states"] == ["PREPARED", "VALIDATED", "PROBED", "SEALED"]
    assert [(g["gate"], g["status"]) for g in record["gates"]] == [
        ("V", "PASS"), ("T", "PASS"), ("A", "PASS"), ("L", "PASS"), ("S", "PASS")]
    assert record["seal"] == seal(record) == record["gates"][-1]["evidence_sha256"]
    assert calls[0] == PROBE
    assert calls[1] == PYTEST + ("tests/test_work_list.py",)
    assert calls[2] == PYTEST + AUTHORITY_TESTS and calls[3] == LINT
    tampered = {**record, "head": "c" * 40}
    assert seal(tampered) != record["seal"]


def test_a_failing_test_rejects_with_its_real_output(tree):
    record = asyncio.run(build_generation(
        tree, "gus/x", CLEAN, RECORDED, "f" * 64,
        _runner([(PYTEST + ("tests/test_work_list.py",), (1, "1 failed: assert 2 == 3"))], [])))
    assert record["state"] == "REJECTED" and not record["seal"]
    t_gate = next(g for g in record["gates"] if g["gate"] == "T")
    assert t_gate["status"] == "FAIL" and "assert 2 == 3" in t_gate["output"]


def test_without_a_usable_sandbox_python_nothing_is_sealed(tree):
    record = asyncio.run(build_generation(
        tree, "gus/x", CLEAN, RECORDED, "f" * 64,
        _runner([(PROBE, (1, "No module named 'textual'"))], [])))
    assert record["state"] == "REJECTED"
    assert [(g["gate"], g["status"]) for g in record["gates"]][1:] == [
        ("T", "NOT_RUN"), ("A", "NOT_RUN"), ("L", "NOT_RUN")]


def test_v_failure_stops_before_any_command_runs(tree):
    calls = []
    record = asyncio.run(build_generation(tree, "gus/x", {**CLEAN, "clean": False}, RECORDED,
                                          "f" * 64, _runner([], calls)))
    assert record["state"] == "REJECTED" and calls == []


def test_uncovered_code_does_not_pass_t(tree):
    changes = {**CLEAN, "changes": [{"status": "M", "path": "src/isycode/untested.py"}]}
    (tree / "src" / "isycode" / "untested.py").write_text("y = 1\n", encoding="utf-8")
    record = asyncio.run(build_generation(tree, "gus/x", changes, RECORDED, "f" * 64, _runner([], [])))
    t_gate = next(g for g in record["gates"] if g["gate"] == "T")
    assert record["state"] == "REJECTED" and "no test covers" in t_gate["detail"]


def test_without_ruff_lint_falls_back_to_a_compile_check_and_says_so(tree):
    calls = []
    record = asyncio.run(build_generation(
        tree, "gus/x", CLEAN, RECORDED, "f" * 64,
        _runner([(LINT, (1, "/usr/bin/python3: No module named ruff"))], calls)))
    lint = next(g for g in record["gates"] if g["gate"] == "L")
    assert lint["status"] == "PASS" and "ruff is not installed" in lint["detail"]
    assert calls[-1][:4] == ("python3", "-B", "-m", "py_compile")


@pytest.mark.skipif(git_executable() is None, reason="git is not installed")
def test_the_git_owner_reads_the_committed_range_and_the_boundary_guards_it(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "a.py").write_text("a = 1\n" * 20)
    (root / "b.py").write_text("b = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    base = _git(root, "rev-parse", "HEAD").strip()
    _git(root, "switch", "-qc", "gus/work")
    _git(root, "mv", "a.py", "renamed.py")
    (root / "b.py").write_text("b = 2\n")
    _git(root, "commit", "-qam", "work")
    authority = WorkspaceAuthority(root.resolve(), state_directory=tmp_path / "state" / "authority")
    authority.set_mode("classic")
    owner = GitOwner(root, authority, ActionApprovalStore())
    outcome = owner.generation_changes(base)
    assert outcome.decision == "ALLOW"
    result = json.loads(outcome.text)
    assert result["clean"] and result["base"] == base
    assert {"status": "R", "from": "a.py", "path": "renamed.py"} in result["changes"]
    assert {"status": "M", "path": "b.py"} in result["changes"]
    (root / "b.py").write_text("b = 3\n")
    assert json.loads(owner.generation_changes(base).text)["clean"] is False

    gate = ProductActionGate(root.resolve(), authority, owner_id="workspace_git")
    params = dict(owner._request("git.diff", staged=False, path=".", since=base).parameters)
    for change in ({"since": "HEAD~1"}, {"since": "x" * 40}, {"path": "src"}, {"staged": True}):
        request = ActionRequest("git.diff", root.resolve(), str(root.resolve()), {**params, **change},
                                execution_owner="workspace_git")
        _, decision = gate.authorize(request)
        assert not decision.allowed, change


@pytest.mark.skipif(git_executable() is None, reason="git is not installed")
def test_gus_seal_in_the_tui_records_the_branch_start_and_seals_after_confirmation(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    from test_gus_session import _checkout
    from isycode.gus_session import GusState
    from isycode.action_runtime import ActionOutcome
    from isycode.tui import TUIApp
    from isycode.tui_screens_approval import GusBranchApprovalScreen, ConfirmScreen
    root = configure(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    _checkout(root)
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_notes.py").write_text("def test_ok():\n    assert True\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    ran = []

    class FakeCommands:
        def __init__(self, workspace, authority, approvals):
            self.root = workspace

        def prepare(self, argv, cwd=".", timeout_s=600):
            ran.append(tuple(argv))
            return type("Preview", (), {"request": ActionRequest(
                "workspace.command.run", self.root, str(self.root), {"argv": list(argv)},
                execution_owner="workspace_command")})()

        async def run(self, preview, approval):
            return ActionOutcome(json.dumps({"exit_code": 0, "output": "passed", "timed_out": False}),
                                 "ALLOW", None, "ok")

    monkeypatch.setattr("isycode.command_runner.CommandRunOwner", FakeCommands)

    async def until(pilot, condition, what):
        for _ in range(200):
            if condition():
                return
            await pilot.pause(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            task = asyncio.ensure_future(app._create_gus_branch("notes"))
            await until(pilot, lambda: isinstance(app.screen, GusBranchApprovalScreen), "the branch approval")
            app.screen.dismiss(True)
            assert await asyncio.wait_for(task, 10) == "gus/notes"
            assert GusState(root).branch("gus/notes")["base"] == _git(root, "rev-parse", "HEAD").strip()
            (root / "tests" / "test_notes.py").write_text("def test_ok():\n    assert 1 == 1\n")
            _git(root, "commit", "-qam", "GUS change")

            task = asyncio.ensure_future(app._seal_gus_generation())
            await until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "the seal confirmation")
            app.screen.dismiss(True)
            record = await asyncio.wait_for(task, 20)
            assert record["state"] == "SEALED", record["gates"]
            assert ran[0] == PROBE and ("tests/test_notes.py" in ran[1])
            assert GusState(root).generations()[-1]["seal"] == record["seal"]

    with capsys.disabled():
        asyncio.run(scenario())
