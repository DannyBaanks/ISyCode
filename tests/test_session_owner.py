"""Saving and resuming conversations is owned, granted, redacted and journaled."""
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import ProductActionGate
from isycode.security import ActionRequest
from isycode.session_owner import ChatSessionOwner
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture
def sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    store_root = tmp_path / "state" / "sessions" / "a"
    owner = ChatSessionOwner(root, authority, store_root)
    return owner, authority, root.resolve(), store_root


def grant(authority):
    authority.set_grant("session.create", enabled=True)
    authority.set_grant("session.resume", enabled=True)


def test_nothing_is_written_or_listed_without_the_grant(sessions):
    owner, _, _, store_root = sessions
    outcome, session_id = owner.record(None, "user", "hello")
    assert outcome.decision == "DENY" and session_id is None
    assert list(store_root.glob("*.json")) == []
    assert owner.list_conversations()[0].decision == "DENY"


def test_save_list_and_resume_round_trip_with_receipts(sessions):
    owner, authority, root, _ = sessions
    grant(authority)
    first, session_id = owner.record(None, "user", "Fix the parser for nested configs")
    second, same = owner.record(session_id, "assistant", "I will read it first.")
    assert first.decision == second.decision == "ALLOW" and same == session_id
    assert first.receipt and second.receipt

    listed, found = owner.list_conversations()
    assert listed.decision == "ALLOW"
    assert [item.session_id for item in found] == [session_id]
    assert found[0].title == "Fix the parser for nested configs"

    loaded, session = owner.resume(session_id)
    assert loaded.decision == "ALLOW"
    assert [m["role"] for m in session.messages] == ["user", "assistant"]
    assert ActionAuditJournal(root).verify().status == "PASS"


def test_secrets_are_redacted_before_they_reach_disk(sessions):
    owner, authority, _, store_root = sessions
    grant(authority)
    secret = "sk-" + "A" * 40
    _, session_id = owner.record(None, "user", f"my key is {secret} and api_key=hunter2")
    stored = b"".join(path.read_bytes() for path in store_root.glob("*.json"))
    assert secret.encode() not in stored and b"hunter2" not in stored
    assert b"[redacted]" in stored


def test_revoking_the_grant_stops_saving_immediately(sessions):
    owner, authority, _, _ = sessions
    grant(authority)
    _, session_id = owner.record(None, "user", "one")
    authority.set_grant("session.create", enabled=False)
    outcome, _ = owner.record(session_id, "user", "two")
    assert outcome.decision == "DENY"
    assert len(owner.resume(session_id)[1].messages) == 1


def test_workspaces_do_not_share_transcripts(sessions, tmp_path):
    owner, authority, _, _ = sessions
    grant(authority)
    owner.record(None, "user", "only in A")
    other_root = tmp_path / "other"
    other_root.mkdir()
    other_authority = WorkspaceAuthority(other_root, state_directory=tmp_path / "authority")
    grant(other_authority)
    other = ChatSessionOwner(other_root, other_authority, tmp_path / "state" / "sessions" / "b")
    assert other.list_conversations()[1] == []


def test_unknown_or_malformed_session_ids_are_refused(sessions):
    owner, authority, _, _ = sessions
    grant(authority)
    assert owner.resume("../../etc/passwd")[0].decision == "DENY"
    assert owner.resume("0" * 32)[0].decision == "ERROR"
    assert owner.record("not-a-session", "user", "x")[0].decision == "DENY"
    assert owner.record(None, "system", "x")[0].decision == "DENY"


@pytest.mark.parametrize("action, target, parameters", [
    ("session.create", "a" * 32, {"operation": "create", "session_id": "b" * 32, "role": "user",
                                  "content_sha256": "c" * 64, "size": 1}),
    ("session.create", "a" * 32, {"operation": "delete", "session_id": "a" * 32, "role": "user",
                                  "content_sha256": "c" * 64, "size": 1}),
    ("session.create", "a" * 32, {"operation": "append", "session_id": "a" * 32, "role": "system",
                                  "content_sha256": "c" * 64, "size": 1}),
    ("session.resume", "elsewhere", {"operation": "list"}),
    ("session.resume", "a" * 32, {"operation": "load", "session_id": "a" * 32, "path": "/etc"}),
])
def test_sentinel_rejects_forged_session_requests(sessions, action, target, parameters):
    _, authority, root, _ = sessions
    grant(authority)
    gate = ProductActionGate(root, authority, owner_id="chat_sessions")
    request = ActionRequest(action, root, target, parameters, execution_owner="chat_sessions")
    assert not gate.authorize(request)[1].allowed
