"""The action journal rotates into chained segments instead of filling up."""
import hashlib
import secrets
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import ActionReceipt, ProductActionGate
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture
def journal_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(ActionAuditJournal, "SEGMENT_BYTES", 4096)
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("provider.request", enabled=True, network_hosts=["api.example.com"])
    gate = ProductActionGate(root, authority, owner_id="provider_network")
    return root, gate


def _effect(root, gate, n):
    request = ActionRequest("provider.request", root, "api.example.com",
                            {"url": "https://api.example.com/v1", "n": n},
                            execution_owner="provider_network")
    _, decision = gate.authorize(request)
    assert decision.allowed
    receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
                            "ALLOW", "SUCCESS", hashlib.sha256(str(n).encode()).hexdigest())
    assert gate.persist_receipt(request, receipt)


def test_journal_rotates_into_verifiable_chained_segments(journal_env):
    root, gate = journal_env
    for n in range(40):
        _effect(root, gate, n)
    journal = ActionAuditJournal(root)
    sealed = journal._sealed_segments()
    assert len(sealed) >= 3
    assert all(path.stat().st_size <= 4096 + 16 * 1024 for path in sealed)
    report = journal.verify()
    assert report.status == "PASS", report.reason
    assert report.decisions == 40 and report.receipts == 40


def test_tampering_with_a_sealed_segment_is_detected(journal_env):
    root, gate = journal_env
    for n in range(30):
        _effect(root, gate, n)
    journal = ActionAuditJournal(root)
    first = journal._sealed_segments()[0]
    data = first.read_bytes()
    first.write_bytes(data.replace(b'"n"', b'"m"', 1) if b'"n"' in data else data + b" ")
    first.chmod(0o600)
    assert journal.verify().status == "JOURNAL_INVALID"


def test_a_deleted_middle_segment_is_detected(journal_env):
    root, gate = journal_env
    for n in range(40):
        _effect(root, gate, n)
    journal = ActionAuditJournal(root)
    journal._sealed_segments()[1].unlink()
    assert journal.verify().status == "JOURNAL_INVALID"


def test_a_crash_between_seal_and_new_file_is_anchored_on_the_next_append(journal_env):
    root, gate = journal_env
    for n in range(5):
        _effect(root, gate, n)
    journal = ActionAuditJournal(root)
    # Simulate the rename having happened with no new active file yet.
    journal.path.rename(journal._segment_path(len(journal._sealed_segments()) + 1))
    _effect(root, gate, 99)
    assert journal.path.read_text().splitlines()[0].count('"kind":"segment"') == 1
    assert journal.verify().status == "PASS"


def test_the_journal_no_longer_locks_the_workspace_when_the_old_limit_is_reached(journal_env, monkeypatch):
    root, gate = journal_env
    # Before rotation, reaching MAX_BYTES made every later decision deny.
    monkeypatch.setattr(ActionAuditJournal, "MAX_BYTES", 8192)
    for n in range(60):
        _effect(root, gate, n)
    assert ActionAuditJournal(root).verify().status == "PASS"
