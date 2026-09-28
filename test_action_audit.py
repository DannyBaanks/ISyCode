from pathlib import Path
import hashlib
import json

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import ActionReceipt
from isycode.security import ActionRequest, AuthorityDecision, DecisionCheck, SentinelDecision


def _journal(tmp_path: Path) -> tuple[ActionAuditJournal, ActionRequest]:
    root = tmp_path / "workspace"
    root.mkdir()
    journal = ActionAuditJournal(root, state_directory=tmp_path / "state")
    request = ActionRequest("workspace.files.read", root, target="README.md",
                            execution_owner="workspace_read")
    return journal, request


def test_journal_verifier_accepts_decision_and_matching_receipt(tmp_path):
    journal, request = _journal(tmp_path)
    authority = AuthorityDecision(True, "grant:workspace.files.read", "matched", request.digest)
    decision = SentinelDecision("workspace.files.read", request.digest,
                                (DecisionCheck("Authority", True, "matched"),))
    journal.record_decision(request, authority, decision)
    result = "README content"
    receipt = ActionReceipt("receipt-1", request.action_id, request.digest,
                            "ALLOW", "SUCCESS", __import__("hashlib").sha256(
                                result.encode()).hexdigest())
    journal.record_receipt(request, receipt)

    report = journal.verify()

    assert report.status == "PASS"
    assert report.records == 2
    assert report.receipts == 1


def test_journal_verifier_rejects_tampered_record(tmp_path):
    journal, request = _journal(tmp_path)
    authority = AuthorityDecision(False, "", "no grant", request.digest)
    decision = SentinelDecision("workspace.files.read", request.digest,
                                (DecisionCheck("Authority", False, "no grant"),))
    journal.record_decision(request, authority, decision)
    data = journal.path.read_text(encoding="utf-8").replace('"authority":false', '"authority":true')
    journal.path.write_text(data, encoding="utf-8")

    report = journal.verify()

    assert report.status == "JOURNAL_INVALID"
    assert report.records == 0


def test_journal_verifier_rejects_truncated_final_line(tmp_path):
    journal, request = _journal(tmp_path)
    authority = AuthorityDecision(False, "", "no grant", request.digest)
    decision = SentinelDecision("workspace.files.read", request.digest,
                                (DecisionCheck("Authority", False, "no grant"),))
    journal.record_decision(request, authority, decision)
    journal.path.write_bytes(journal.path.read_bytes().rstrip(b"\n"))

    assert journal.verify().status == "JOURNAL_INVALID"


def test_read_only_inspection_does_not_create_state_or_expose_request_data(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    state = tmp_path / "missing-state"
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))

    report = ActionAuditJournal.for_read_only_inspection(root).verify()

    assert report.status == "NOT_VERIFIABLE"
    assert report.records == report.unverifiable == 0
    assert not state.exists()


def test_journal_recent_view_contains_only_redacted_metadata(tmp_path):
    journal, request = _journal(tmp_path)
    authority = AuthorityDecision(False, "", "no grant", request.digest)
    decision = SentinelDecision("workspace.files.read", request.digest,
                                (DecisionCheck("Authority", False, "no grant"),))
    journal.record_decision(request, authority, decision)

    report = journal.verify()
    rendered = repr(report.recent)

    assert report.status == "PASS"
    assert "README.md" not in rendered
    assert "content" not in rendered
    assert request.digest[:12] in rendered


def test_journal_verifier_rejects_broken_previous_link(tmp_path):
    journal, request = _journal(tmp_path)
    body = {
        "kind": "decision", "version": 1, "time": 1.0,
        "workspace": "0" * 32, "action": request.action_id,
        "owner": "workspace_read", "request_digest": request.digest,
        "authority": False, "sentinel": "DENY", "failed_checks": [],
        "previous": "f" * 64,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["digest"] = hashlib.sha256(("f" * 64 + canonical).encode()).hexdigest()
    journal.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    journal.path.write_text(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
                            encoding="utf-8")

    assert journal.verify().status == "JOURNAL_INVALID"


def test_journal_verifier_rejects_replayed_receipt_id(tmp_path):
    journal, request = _journal(tmp_path)
    authority = AuthorityDecision(True, "grant:workspace.files.read", "matched", request.digest)
    decision = SentinelDecision("workspace.files.read", request.digest,
                                (DecisionCheck("Authority", True, "matched"),))
    journal.record_decision(request, authority, decision)
    receipt = ActionReceipt("receipt-replay", request.action_id, request.digest,
                            "ALLOW", "SUCCESS", "a" * 64)
    journal.record_receipt(request, receipt)
    journal.record_receipt(request, receipt)

    assert journal.verify().status == "JOURNAL_INVALID"
