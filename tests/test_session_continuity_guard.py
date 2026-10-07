"""Two continuities of one conversation never merge or overwrite each other silently.

Each "instance" below is a separate Python process with its own ChatSessionOwner
(tests/session_peer.py), the same shape as two ISyCode windows on one workspace.
"""
import json
import time
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.chat_sessions import ChatSessionStore, SessionDiverged
from isycode.security import ActionRequest
from isycode.session_owner import DIVERGED_REASON, ChatSessionOwner
from isycode.workspace_authority import WorkspaceAuthority
from session_peer_client import PeerProcess

Peer = PeerProcess


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("")
    WorkspaceAuthority(root).set_mode("classic")
    sessions = tmp_path / "sessions"
    peers = []

    def spawn(**extra_env):
        peer = PeerProcess(root, sessions, **extra_env)
        peers.append(peer)
        return peer

    owner = ChatSessionOwner(root, WorkspaceAuthority(root), sessions)
    _, sid = owner.record(None, "user", "Refactoriza el parser")
    owner.record(sid, "assistant", "Listo.", state={"conversation_summary": "parser hecho"})
    yield owner, sid, spawn, root
    for peer in peers:
        peer.close()


def transcript(owner, sid):
    return [message["content"] for message in owner.store.load(sid).messages]


def receipt_digests(root):
    """request_digest of every receipt in the private journal (all segments)."""
    digests = set()
    for path in Path(ActionAuditJournal(root).path).parent.glob("*"):
        if not path.is_file():
            continue
        for line in path.read_text(errors="ignore").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("kind") == "receipt":
                digests.add(record.get("request_digest"))
    return digests


def event_digest(root, sid, operation, expected, current, fork_id=""):
    """The journal keeps request digests only, so an event is recognized by
    recomputing the digest of the exact request it must have been."""
    params = {"operation": operation, "session_id": sid,
              "expected_revision": expected or "", "current_revision": current or ""}
    if operation == "divergence_forked":
        params["fork_id"] = fork_id
    return ActionRequest("session.resume", root.resolve(), sid, params,
                         execution_owner="chat_sessions").digest


# ── T1 ────────────────────────────────────────────────────────────────
def test_t1_single_continuity_saves_normally(workspace):
    owner, sid, spawn, _ = workspace
    a = spawn()
    assert a(op="resume", sid=sid)["decision"] == "ALLOW"
    assert a(op="record", sid=sid, role="user", content="A1")["decision"] == "ALLOW"
    assert a(op="record", sid=sid, role="assistant", content="A2")["decision"] == "ALLOW"
    assert transcript(owner, sid)[-2:] == ["A1", "A2"]
    assert a(op="status", sid=sid)["diverged"] is False


# ── T2 ────────────────────────────────────────────────────────────────
def test_t2_stale_continuity_cannot_write(workspace):
    owner, sid, spawn, root = workspace
    a, b = spawn(), spawn()
    a(op="resume", sid=sid)
    b(op="resume", sid=sid)
    assert b(op="record", sid=sid, role="user", content="B: borra el parser")["decision"] == "ALLOW"
    before = owner.store._read_bytes(sid)
    reply = a(op="record", sid=sid, role="user", content="A: agrega tests")
    assert reply["decision"] == "DENY" and reply["reason"].startswith(DIVERGED_REASON)
    assert owner.store._read_bytes(sid) == before  # X not modified by A
    assert "A: agrega tests" not in transcript(owner, sid)
    assert a(op="status", sid=sid)["diverged"] is True


# ── T3 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slow", ["", "0.15"])
def test_t3_racing_writers_one_wins_the_other_sees_divergence(workspace, slow):
    owner, sid, spawn, _ = workspace
    for round_number in range(8):
        a, b = spawn(ISYCODE_TEST_SLOW_WRITE=slow), spawn(ISYCODE_TEST_SLOW_WRITE=slow)
        a(op="resume", sid=sid)
        b(op="resume", sid=sid)
        start = time.time() + 0.3
        a.send(op="record", sid=sid, role="user", content=f"A{round_number}", wait_until=start)
        b.send(op="record", sid=sid, role="user", content=f"B{round_number}", wait_until=start)
        replies = {"A": a.receive(), "B": b.receive()}
        winners = [name for name, reply in replies.items() if reply["decision"] == "ALLOW"]
        assert len(winners) == 1, replies
        loser = "B" if winners == ["A"] else "A"
        assert replies[loser]["reason"].startswith(DIVERGED_REASON)
        saved = transcript(owner, sid)
        assert saved[-1] == f"{winners[0]}{round_number}"
        assert f"{loser}{round_number}" not in saved  # nothing merged that nobody lived
        a.close()
        b.close()


def test_t3b_concurrent_read_modify_write_never_loses_a_message(workspace):
    """Before the lock, two load→append→save cycles could drop one message silently."""
    owner, sid, spawn, _ = workspace
    a, b = spawn(ISYCODE_TEST_SLOW_WRITE="0.01"), spawn(ISYCODE_TEST_SLOW_WRITE="0.01")
    start = time.time() + 0.3
    for i in range(15):
        a.send(op="store_append", sid=sid, role="user", content=f"a{i}", wait_until=start)
        b.send(op="store_append", sid=sid, role="user", content=f"b{i}", wait_until=start)
    for peer in (a, b):
        for _ in range(15):
            assert peer.receive()["decision"] == "ALLOW"
    saved = transcript(owner, sid)
    assert {f"a{i}" for i in range(15)} | {f"b{i}" for i in range(15)} <= set(saved)
    assert len(saved) == 2 + 30


# ── T4 ────────────────────────────────────────────────────────────────
def test_t4_state_only_change_is_divergence(workspace):
    owner, sid, spawn, _ = workspace
    a, b = spawn(), spawn()
    a(op="resume", sid=sid)
    b(op="resume", sid=sid)
    count = len(transcript(owner, sid))
    state = json.dumps({"conversation_summary": "B cambió el resumen", "draft": "borrador de B"})
    assert b(op="manage", operation="state", sid=sid, data=state)["decision"] == "ALLOW"
    assert len(transcript(owner, sid)) == count  # same message count
    reply = a(op="manage", operation="state", sid=sid,
              data=json.dumps({"conversation_summary": "A"}))
    assert reply["decision"] == "DENY" and reply["reason"].startswith(DIVERGED_REASON)
    assert owner.store.load(sid).state["conversation_summary"] == "B cambió el resumen"


# ── T5 ────────────────────────────────────────────────────────────────
def test_t5_fork_keeps_the_original_and_stores_this_continuity(workspace):
    owner, sid, spawn, root = workspace
    a, b = spawn(), spawn()
    a(op="resume", sid=sid)
    b(op="resume", sid=sid)
    b(op="record", sid=sid, role="user", content="B: borra")
    original = owner.store._read_bytes(sid)
    a(op="record", sid=sid, role="user", content="A: tests")  # diverges
    mine = [{"role": "user", "content": "Refactoriza el parser"},
            {"role": "assistant", "content": "Listo."},
            {"role": "user", "content": "A: tests"}]
    reply = a(op="fork_mine", sid=sid, messages=mine, state={"conversation_summary": "A"},
              title="Refactor")
    assert reply["decision"] == "ALLOW"
    fork = owner.store.load(reply["sid"])
    assert owner.store._read_bytes(sid) == original
    assert [m["content"] for m in fork.messages] == [m["content"] for m in mine]
    assert fork.title.startswith("Fork:")
    assert a(op="status", sid=sid)["diverged"] is False
    # The fork is A's new base: it keeps saving there.
    assert a(op="record", sid=reply["sid"], role="assistant", content="A: hecho")["decision"] == "ALLOW"


# ── T6 ────────────────────────────────────────────────────────────────
def test_t6_reload_loads_exactly_the_persisted_state(workspace):
    owner, sid, spawn, _ = workspace
    a, b = spawn(), spawn()
    a(op="resume", sid=sid)
    b(op="resume", sid=sid)
    b(op="record", sid=sid, role="user", content="B: borra", state={"draft": "de B"})
    a(op="record", sid=sid, role="user", content="A: tests")
    reply = a(op="reload", sid=sid)
    stored = owner.store.load(sid)
    assert reply["messages"] == [m["content"] for m in stored.messages]
    assert reply["state"] == stored.state
    assert a(op="status", sid=sid) == {"diverged": False, "base": owner.store.revision(sid)}
    assert a(op="record", sid=sid, role="user", content="A: sigo")["decision"] == "ALLOW"


# ── T7 ────────────────────────────────────────────────────────────────
def test_t7_continuing_without_saving_never_writes_the_original(workspace):
    owner, sid, spawn, _ = workspace
    a, b = spawn(), spawn()
    a(op="resume", sid=sid)
    b(op="resume", sid=sid)
    b(op="record", sid=sid, role="user", content="B: borra")
    a(op="record", sid=sid, role="user", content="A: tests")
    a(op="keep_unsaved", sid=sid)
    frozen = owner.store._read_bytes(sid)
    for turn in range(3):
        assert a(op="record", sid=sid, role="user", content=f"A turn {turn}")["decision"] == "DENY"
        assert a(op="manage", operation="state", sid=sid,
                 data=json.dumps({"draft": "x"}))["decision"] == "DENY"
        assert a(op="manage", operation="rename", sid=sid, data="A")["decision"] == "DENY"
    assert owner.store._read_bytes(sid) == frozen
    # An incidental resume (for example to look at it) does not re-arm writes.
    a(op="resume", sid=sid)
    assert a(op="record", sid=sid, role="user", content="A late")["decision"] == "DENY"
    # B, which never diverged, keeps working normally.
    assert b(op="record", sid=sid, role="user", content="B: sigue")["decision"] == "ALLOW"


# ── T8 / T9 ───────────────────────────────────────────────────────────
def test_t8_t9_unrelated_conversations_in_one_workspace_do_not_interfere(workspace):
    owner, sid, spawn, _ = workspace
    _, other = owner.record(None, "user", "Otra conversación")
    a, b = spawn(), spawn()
    a(op="resume", sid=sid)
    b(op="resume", sid=other)
    for turn in range(3):
        assert a(op="record", sid=sid, role="user", content=f"a{turn}")["decision"] == "ALLOW"
        assert b(op="record", sid=other, role="user", content=f"b{turn}")["decision"] == "ALLOW"
    assert a(op="status", sid=sid)["diverged"] is False
    assert b(op="status", sid=other)["diverged"] is False


# ── Every writer goes through the same guard ──────────────────────────
@pytest.mark.parametrize("operation, data", [
    ("rename", "Nuevo título"),
    ("state", json.dumps({"draft": "otro"})),
    ("auto_title", "Título automático"),
])
def test_every_manage_writer_is_guarded(workspace, operation, data):
    owner, sid, spawn, _ = workspace
    a, b = spawn(), spawn()
    a(op="resume", sid=sid)
    b(op="resume", sid=sid)
    b(op="record", sid=sid, role="user", content="B")
    before = owner.store._read_bytes(sid)
    reply = a(op="manage", operation=operation, sid=sid, data=data)
    assert reply["decision"] == "DENY" and reply["reason"].startswith(DIVERGED_REASON)
    assert owner.store._read_bytes(sid) == before


def test_delete_refuses_a_transcript_changed_after_review(workspace):
    from isycode.action_runtime import SessionDeleteOwner
    from isycode.approvals import ActionApprovalStore

    owner, sid, spawn, root = workspace
    reviewed = owner.store.revision(sid)
    b = spawn()
    b(op="resume", sid=sid)
    b(op="record", sid=sid, role="user", content="B escribió después de la revisión")
    approvals = ActionApprovalStore()
    request = ActionRequest("session.delete", root.resolve(), sid,
                            {"session_id": sid, "title": "t"}, execution_owner="session_delete")
    authority = WorkspaceAuthority(root)
    authority.set_grant("session.delete", enabled=True, targets=[sid])
    result = SessionDeleteOwner(root, authority, owner.store, approvals).delete(
        sid, "t", approvals.issue(request), expected_revision=reviewed)
    assert result.decision == "DENY" and DIVERGED_REASON in result.reason
    assert owner.store.load(sid).messages[-1]["content"] == "B escribió después de la revisión"


def test_store_level_conditional_write_and_lock_are_reentrant(tmp_path):
    store = ChatSessionStore(tmp_path / "s")
    session = store.create("hola")
    revision = store.revision(session.session_id)
    with store.write_lock(), store.write_lock():  # re-entrant within one thread
        store.save(session, expected_revision=revision)
    with pytest.raises(SessionDiverged):
        store.save(session, expected_revision=revision)  # file moved on after that save


def test_divergence_events_are_journaled_without_content(workspace):
    owner, sid, spawn, root = workspace
    a, b = spawn(), spawn()
    a(op="resume", sid=sid)
    base = a(op="status", sid=sid)["base"]
    b(op="resume", sid=sid)
    b(op="record", sid=sid, role="user", content="SECRETO-DE-B")
    after_b = owner.store.revision(sid)
    a(op="record", sid=sid, role="user", content="SECRETO-DE-A")
    a(op="keep_unsaved", sid=sid)
    digests = receipt_digests(root)
    assert event_digest(root, sid, "divergence_detected", base, after_b) in digests
    assert event_digest(root, sid, "divergence_unsaved", base, after_b) in digests
    journal_text = "".join(path.read_text(errors="ignore")
                           for path in Path(ActionAuditJournal(root).path).parent.glob("*")
                           if path.is_file())
    assert "SECRETO-DE-A" not in journal_text and "SECRETO-DE-B" not in journal_text
    assert ActionAuditJournal(root).verify().status == "PASS"


def test_old_sessions_stay_readable_and_the_format_is_unchanged(tmp_path):
    store = ChatSessionStore(tmp_path / "s")
    legacy = {"version": 1, "session_id": "a" * 32, "title": "vieja", "created_at": 1.0,
              "updated_at": 1.0, "messages": [{"role": "user", "content": "hola"}]}
    (store.root / ("a" * 32 + ".json")).write_text(json.dumps(legacy))
    assert store.load("a" * 32).messages[0]["content"] == "hola"
    written = json.loads(store._write(store.create("x"))[0].read_text())
    assert set(written) == {"version", "session_id", "title", "messages", "created_at",
                            "updated_at", "state", "title_manual"}


def test_own_writes_after_review_do_not_block_delete_but_foreign_ones_do(workspace):
    from isycode.action_runtime import SessionDeleteOwner
    from isycode.approvals import ActionApprovalStore

    owner, sid, spawn, root = workspace
    owner.resume(sid)
    _, _, reviewed = owner.review(sid)
    owner.manage("state", sid, json.dumps({"draft": "my own draft save"}))  # same instance
    expected = owner.base_revision(sid)
    assert expected != reviewed
    approvals = ActionApprovalStore()
    authority = WorkspaceAuthority(root)
    authority.set_grant("session.delete", enabled=True, targets=[sid])
    request = ActionRequest("session.delete", root.resolve(), sid,
                            {"session_id": sid, "title": "t"}, execution_owner="session_delete")
    deleted = SessionDeleteOwner(root, authority, owner.store, approvals).delete(
        sid, "t", approvals.issue(request), expected_revision=expected)
    assert deleted.decision == "ALLOW"
