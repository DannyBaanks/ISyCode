from pathlib import Path
import hashlib
import json
import pytest

from isycode.action_audit import ActionAuditError, ActionAuditJournal
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
                                (DecisionCheck("Authority", True, "matched"),
                                 DecisionCheck("WorkspaceReadBoundary", True, "inside root")))
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
    assert report.recent[0]["checks"] == [
        {"name": "Authority", "passed": True},
        {"name": "WorkspaceReadBoundary", "passed": True},
    ]
    assert "inside root" not in repr(report.recent)


def test_journal_accepts_redacted_tailscale_failure_receipt(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    journal = ActionAuditJournal(root, state_directory=tmp_path / "state")
    request = ActionRequest("tailscale.install", root, "tailscale",
                            execution_owner="tailscale_package_install")
    authority = AuthorityDecision(True, "grant:tailscale.install", "matched", request.digest)
    decision = SentinelDecision("tailscale.install", request.digest,
                                (DecisionCheck("Authority", True, "matched"),))
    journal.record_decision(request, authority, decision)
    receipt = ActionReceipt("receipt-failure", request.action_id, request.digest,
                            "ALLOW", "FAILURE", hashlib.sha256(b"failed:transaction").hexdigest())

    journal.record_receipt(request, receipt)
    report = journal.verify()

    assert report.status == "PASS"
    assert report.receipts == 1
    assert report.recent[-1]["outcome"] == "FAILURE"
    assert "token=" not in journal.path.read_text(encoding="utf-8")


def test_journal_accepts_redacted_tailscale_login_failure_receipt(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    journal = ActionAuditJournal(root, state_directory=tmp_path / "state")
    request = ActionRequest("tailscale.login", root, "tailscale",
                            execution_owner="tailscale_login")
    authority = AuthorityDecision(True, "grant:tailscale.login", "matched", request.digest)
    decision = SentinelDecision("tailscale.login", request.digest,
                                (DecisionCheck("Authority", True, "matched"),))
    journal.record_decision(request, authority, decision)
    receipt = ActionReceipt("receipt-login-failure", request.action_id, request.digest,
                            "ALLOW", "FAILURE", hashlib.sha256(b"failed:login").hexdigest())

    journal.record_receipt(request, receipt)
    report = journal.verify()

    assert report.status == "PASS"
    assert report.receipts == 1


@pytest.mark.parametrize("action", [
    "tailscale.serve.enable", "tailscale.serve.disable",
])
def test_journal_accepts_redacted_tailscale_serve_failure_receipts(tmp_path, action):
    root = tmp_path / "workspace"
    root.mkdir()
    journal = ActionAuditJournal(root, state_directory=tmp_path / action.replace(".", "-"))
    request = ActionRequest(action, root, "tailscale", execution_owner="tailscale_serve")
    authority = AuthorityDecision(True, f"grant:{action}", "matched", request.digest)
    decision = SentinelDecision(action, request.digest,
                                (DecisionCheck("Authority", True, "matched"),))
    journal.record_decision(request, authority, decision)
    receipt = ActionReceipt("receipt-" + action.replace(".", "-"), action,
                            request.digest, "ALLOW", "FAILURE",
                            hashlib.sha256(b"failed:serve").hexdigest())

    journal.record_receipt(request, receipt)

    assert journal.verify().status == "PASS"


def test_journal_rejects_decision_results_bound_to_another_request(tmp_path):
    journal, request = _journal(tmp_path)
    other = ActionRequest("workspace.files.read", request.workspace_root,
                          target="other.txt", execution_owner="workspace_read")
    authority = AuthorityDecision(True, "grant:workspace.files.read", "matched", other.digest)
    decision = SentinelDecision(request.action_id, request.digest,
                                (DecisionCheck("Authority", True, "matched"),))

    try:
        journal.record_decision(request, authority, decision)
    except ActionAuditError as exc:
        assert "immutable request" in str(exc)
    else:
        raise AssertionError("journal accepted an Authority result for a different request")


def test_journal_rejects_sentinel_result_for_another_action(tmp_path):
    journal, request = _journal(tmp_path)
    authority = AuthorityDecision(True, "grant:workspace.files.read", "matched", request.digest)
    decision = SentinelDecision("workspace.files.search", request.digest,
                                (DecisionCheck("Authority", True, "matched"),))

    try:
        journal.record_decision(request, authority, decision)
    except ActionAuditError as exc:
        assert "immutable request" in str(exc)
    else:
        raise AssertionError("journal accepted a Sentinel result for another action")


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
    # Without private permissions the verifier rejects the file before checking
    # the chain, and this test would pass without testing what it names.
    journal.path.chmod(0o600)

    report = journal.verify()
    assert report.status == "JOURNAL_INVALID"
    assert "verification failed" in report.reason


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


def _write_chained_decision(journal, request, **overrides):
    """Write one well-formed, correctly chained decision record on disk."""
    body = {
        "kind": "decision", "version": 1, "time": 1.0,
        "workspace": "0" * 32, "action": request.action_id,
        "owner": "workspace_read", "request_digest": request.digest,
        "authority": True, "sentinel": "ALLOW", "failed_checks": [],
        "checks": [], "previous": "0" * 64,
    }
    body.update(overrides)
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["digest"] = hashlib.sha256(("0" * 64 + canonical).encode()).hexdigest()
    journal.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    journal.path.write_text(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
                            encoding="utf-8")
    # The journal refuses a file other accounts can read; without this the
    # verifier would reject the file before it ever looked at its contents.
    journal.path.chmod(0o600)


def test_decision_records_the_effect_class_and_policy_version(tmp_path):
    """Audit 2026-10-09 F2: a decision must carry its own classification."""
    from isycode.effect_policy import POLICY_VERSION, effect_class

    journal, request = _journal(tmp_path)
    authority = AuthorityDecision(True, "grant:workspace.files.read", "matched", request.digest)
    decision = SentinelDecision("workspace.files.read", request.digest,
                                (DecisionCheck("Authority", True, "matched"),))
    journal.record_decision(request, authority, decision)

    written = json.loads(journal.path.read_text(encoding="utf-8").splitlines()[0])
    assert written["effect"] == effect_class("workspace.files.read") == "read"
    assert written["policy_version"] == POLICY_VERSION
    report = journal.verify()
    assert report.status == "PASS" and report.unverifiable == 0
    assert report.recent[0]["effect"] == "read"


def test_the_recorded_effect_class_follows_the_catalog(tmp_path):
    """The label is the action's real class, not a constant."""
    from isycode.effect_policy import effect_class

    journal, _ = _journal(tmp_path)
    root = tmp_path / "workspace"
    for action, owner in (("workspace.files.read", "workspace_read"),
                          ("workspace.files.delete", "workspace_write"),
                          ("git.push", "workspace_publish")):
        request = ActionRequest(action, root, execution_owner=owner)
        authority = AuthorityDecision(True, f"grant:{action}", "matched", request.digest)
        decision = SentinelDecision(action, request.digest,
                                    (DecisionCheck("Authority", True, "matched"),))
        journal.record_decision(request, authority, decision)

    lines = [json.loads(line) for line in
             journal.path.read_text(encoding="utf-8").splitlines()]
    assert [(item["action"], item["effect"]) for item in lines] == [
        ("workspace.files.read", effect_class("workspace.files.read")),
        ("workspace.files.delete", effect_class("workspace.files.delete")),
        ("git.push", effect_class("git.push")),
    ]


def test_journal_rejects_an_unknown_effect_label(tmp_path):
    journal, request = _journal(tmp_path)
    _write_chained_decision(journal, request, effect="totally-made-up")

    assert journal.verify().status == "JOURNAL_INVALID"


def test_journal_rejects_an_unsupported_policy_version(tmp_path):
    journal, request = _journal(tmp_path)
    _write_chained_decision(journal, request, effect="read", policy_version=99)

    assert journal.verify().status == "JOURNAL_INVALID"


def test_a_legacy_decision_without_effect_identity_still_verifies(tmp_path):
    """Journals written before the field existed must keep verifying."""
    journal, request = _journal(tmp_path)
    body = {
        "kind": "decision", "version": 1, "time": 1.0,
        "workspace": "0" * 32, "action": request.action_id,
        "owner": "workspace_read", "request_digest": request.digest,
        "authority": True, "sentinel": "ALLOW", "failed_checks": [],
        "checks": [], "previous": "0" * 64,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["digest"] = hashlib.sha256(("0" * 64 + canonical).encode()).hexdigest()
    journal.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    journal.path.write_text(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
                            encoding="utf-8")
    journal.path.chmod(0o600)

    report = journal.verify()
    assert report.status == "PASS" and report.records == 1
    assert report.recent[0]["effect"] is None
