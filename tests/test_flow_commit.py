"""GF-04: in Flow, a commit of the turn's own files is attributable; human work is not."""
import subprocess
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.git_owner import GitOwner, git_executable
from isycode.turn_journal import TurnJournal
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner


def _git(root, *args):
    subprocess.run([git_executable(), *args], cwd=root, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={"HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    if git_executable() is None:
        pytest.skip("git is not installed")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "isycode-state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("", encoding="utf-8")
    (root / "tracked.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("flow")
    writer = WorkspaceWriteOwner(root, authority, ActionApprovalStore())
    git = GitOwner(root, authority, ActionApprovalStore())
    return writer, git, root.resolve()


def test_turn_files_are_attributable(repo):
    writer, git, root = repo
    journal = TurnJournal.begin(root)
    assert writer.apply(writer.preview("tracked.py", "x = 2\n"), None).decision == "ALLOW"
    assert writer.apply(writer.preview("fresh.py", "y = 1\n"), None).decision == "ALLOW"

    assert git.turn_attributable(journal, ("tracked.py", "fresh.py")) is True


def test_a_file_the_human_had_dirty_before_the_turn_is_not_attributable(repo):
    writer, git, root = repo
    # Human edits tracked.py and leaves it uncommitted BEFORE the turn.
    (root / "tracked.py").write_text("human work in progress\n", encoding="utf-8")
    journal = TurnJournal.begin(root)
    assert writer.apply(writer.preview("tracked.py", "x = 3\n"), None).decision == "ALLOW"

    # The turn's preimage was the human's dirty content, not HEAD, so it is not attributable.
    assert git.turn_attributable(journal, ("tracked.py",)) is False


def test_a_file_edited_after_the_turn_is_not_attributable(repo):
    writer, git, root = repo
    journal = TurnJournal.begin(root)
    assert writer.apply(writer.preview("fresh.py", "y = 1\n"), None).decision == "ALLOW"
    journal.finish()
    (root / "fresh.py").write_text("y = 2  # human touched it\n", encoding="utf-8")

    assert git.turn_attributable(journal, ("fresh.py",)) is False


def test_a_path_outside_the_turn_is_not_attributable(repo):
    writer, git, root = repo
    journal = TurnJournal.begin(root)
    assert writer.apply(writer.preview("fresh.py", "y = 1\n"), None).decision == "ALLOW"
    (root / "unrelated.py").write_text("z = 9\n", encoding="utf-8")

    assert git.turn_attributable(journal, ("fresh.py", "unrelated.py")) is False
    assert git.turn_attributable(None, ("fresh.py",)) is False


def test_commit_is_not_quiet_by_the_mode_rule_alone(repo):
    # Attributability is decided per commit in the TUI, not by quiet_request:
    # git.commit is never in the quiet action set, so the owner still needs an
    # approval token. The TUI issues it only for an attributable Flow commit.
    from isycode.workspace_trust import QUIET_FLOW_ACTIONS, quiet_flow
    from isycode.security import ActionRequest
    writer, git, root = repo
    assert "git.commit" not in QUIET_FLOW_ACTIONS
    request = ActionRequest("git.commit", root, str(root), {"message": "m"},
                            execution_owner="workspace_git")
    assert quiet_flow(git.authority, request) is False


def test_human_staged_content_requires_review_even_if_worktree_was_clean(repo):
    writer, git, root = repo
    (root / 'tracked.py').write_text('human staged\n')
    _git(root, 'add', 'tracked.py')
    (root / 'tracked.py').write_text('x = 1\n')
    journal = TurnJournal.begin(root)
    assert writer.apply(writer.preview('tracked.py', 'agent\n'), None).decision == 'ALLOW'
    assert git.turn_attributable(journal, ('tracked.py',)) is False
