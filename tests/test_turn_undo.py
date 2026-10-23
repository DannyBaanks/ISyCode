"""GF-03: a Flow turn can be undone, and a later human change is never overwritten."""
import os
import stat
import sys
from pathlib import Path

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.turn_journal import TurnJournal, TurnJournalFull
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner


@pytest.fixture
def flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "isycode-state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("", encoding="utf-8")
    (root / "keep.txt").write_text("original\n", encoding="utf-8")
    (root / "move-me.txt").write_text("to move\n", encoding="utf-8")
    (root / "doomed.txt").write_text("delete me\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    authority.set_mode("flow")
    owner = WorkspaceWriteOwner(root, authority, ActionApprovalStore())
    return owner, root.resolve()


def _run_turn(owner, root):
    journal = TurnJournal.begin(root)
    assert owner.apply(owner.preview("keep.txt", "edited\n"), None).decision == "ALLOW"
    assert owner.apply(owner.preview("new.txt", "brand new\n"), None).decision == "ALLOW"
    assert owner.apply(owner.preview_delete("doomed.txt"), None).decision == "ALLOW"
    assert owner.apply(owner.preview_move("move-me.txt", "moved.txt"), None).decision == "ALLOW"
    journal.finish()
    return journal.turn_id


def test_a_turn_round_trips(flow):
    owner, root = flow
    turn_id = _run_turn(owner, root)
    # The turn landed.
    assert (root / "keep.txt").read_text() == "edited\n"
    assert (root / "new.txt").read_text() == "brand new\n"
    assert not (root / "doomed.txt").exists()
    assert (root / "moved.txt").read_text() == "to move\n" and not (root / "move-me.txt").exists()

    preview = owner.preview_turn_undo(turn_id)
    assert not preview.conflicts and len(preview.steps) == 5
    outcome = owner.apply_turn_undo(preview, None)
    assert outcome.decision == "ALLOW", outcome.reason

    assert (root / "keep.txt").read_text() == "original\n"
    assert not (root / "new.txt").exists()
    assert (root / "doomed.txt").read_text() == "delete me\n"
    assert (root / "move-me.txt").read_text() == "to move\n" and not (root / "moved.txt").exists()


def test_undo_is_refused_twice(flow):
    owner, root = flow
    turn_id = _run_turn(owner, root)
    assert owner.apply_turn_undo(owner.preview_turn_undo(turn_id), None).decision == "ALLOW"
    with pytest.raises(ValueError, match="already undone"):
        owner.preview_turn_undo(turn_id)


def test_a_file_changed_after_the_turn_is_a_conflict_and_is_kept(flow):
    owner, root = flow
    turn_id = _run_turn(owner, root)
    (root / "keep.txt").write_text("human edit after the turn\n", encoding="utf-8")

    preview = owner.preview_turn_undo(turn_id)
    assert "keep.txt" in preview.conflicts
    outcome = owner.apply_turn_undo(preview, None)
    assert outcome.decision == "ALLOW"
    # The human edit is untouched; the rest is restored.
    assert (root / "keep.txt").read_text() == "human edit after the turn\n"
    assert not (root / "new.txt").exists()
    assert (root / "doomed.txt").read_text() == "delete me\n"


@pytest.mark.skipif(os.name == "nt", reason="binary promotion uses the POSIX effect path")
def test_binary_and_permissions_from_a_command_promotion_round_trip(flow, tmp_path, monkeypatch):
    """A command writes a binary file; undo restores the preimage bytes and mode."""
    from isycode.command_runner import CommandRunOwner, sandbox_executable
    if sandbox_executable() is None:
        pytest.skip("bubblewrap is not installed")
    owner, root = flow
    blob = bytes(range(256)) * 8
    (root / "data.bin").write_bytes(blob)
    os.chmod(root / "data.bin", 0o640)
    before_mode = stat.S_IMODE((root / "data.bin").stat().st_mode)
    runner = CommandRunOwner(root, owner.authority, ActionApprovalStore())
    program = str(Path(sys.executable).resolve())
    monkeypatch.setattr("isycode.command_runner.resolve_program", lambda _root, _argv0: "/usr/bin/python3")

    journal = TurnJournal.begin(root)
    preview = runner.prepare(["python3", "-c",
                              "open('data.bin','wb').write(b'OVERWRITTEN BY COMMAND')"])
    import asyncio
    assert asyncio.run(runner.run(preview, None)).decision == "ALLOW"
    journal.finish()
    assert (root / "data.bin").read_bytes() == b"OVERWRITTEN BY COMMAND"

    outcome = owner.apply_turn_undo(owner.preview_turn_undo(journal.turn_id), None)
    assert outcome.decision == "ALLOW", outcome.reason
    assert (root / "data.bin").read_bytes() == blob
    assert stat.S_IMODE((root / "data.bin").stat().st_mode) == before_mode


def test_a_full_turn_budget_denies_and_nothing_lands(flow, monkeypatch):
    owner, root = flow
    monkeypatch.setattr("isycode.turn_journal.MAX_TURN_PATHS", 1)
    TurnJournal.begin(root)
    assert owner.apply(owner.preview("keep.txt", "first\n"), None).decision == "ALLOW"
    denied = owner.apply(owner.preview("new.txt", "second\n"), None)
    assert denied.decision == "DENY" and "undo" in denied.reason
    assert not (root / "new.txt").exists()


def test_undo_while_a_turn_runs_is_refused(flow):
    owner, root = flow
    journal = TurnJournal.begin(root)
    assert owner.apply(owner.preview("keep.txt", "edited\n"), None).decision == "ALLOW"
    with pytest.raises(ValueError, match="still running"):
        owner.preview_turn_undo(journal.turn_id)


def test_outside_a_turn_nothing_is_recorded(flow):
    owner, root = flow
    assert TurnJournal.active(root) is None
    assert owner.apply(owner.preview("keep.txt", "no turn\n"), None).decision == "ALLOW"
    assert (root / "keep.txt").read_text() == "no turn\n"


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission bits')
def test_undo_preserves_a_later_human_permission_change(flow):
    owner, root = flow
    turn_id = _run_turn(owner, root)
    (root / 'keep.txt').chmod(0o600)
    preview = owner.preview_turn_undo(turn_id)
    assert 'keep.txt' in preview.conflicts
    assert owner.apply_turn_undo(preview, None).decision == 'ALLOW'
    assert (root / 'keep.txt').read_text() == 'edited\n'
    assert stat.S_IMODE((root / 'keep.txt').stat().st_mode) == 0o600
