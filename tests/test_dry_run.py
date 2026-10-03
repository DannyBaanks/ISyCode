"""Dry-run evaluates the real boundaries without journaling or executing."""
from __future__ import annotations

from pathlib import Path

from isycode.dry_run import preview_request
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


def test_dry_run_reports_allow_without_persisting_a_decision(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    WorkspaceAuthority(root).set_mode("classic")
    recorded = []
    monkeypatch.setattr(
        "isycode.action_audit.ActionAuditJournal.record_decision",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    request = ActionRequest(
        "session.resume", root.resolve(), "sessions", {"operation": "list"},
        execution_owner="chat_sessions",
    )

    result = preview_request(root, "chat_sessions", request)

    assert result.status == "ALLOW"
    assert result.exit_code == 0
    assert result.grant_id.startswith("grant:")
    assert recorded == []


def test_dry_run_reports_ask_when_only_fresh_approval_is_missing(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    authority = WorkspaceAuthority(root)
    authority.set_mode("classic")
    session_id = "a" * 32
    authority.set_grant("session.delete", enabled=True, targets=[session_id])
    request = ActionRequest(
        "session.delete", root.resolve(), session_id,
        {"session_id": session_id, "title": "Fixture"},
        execution_owner="session_delete",
    )

    result = preview_request(root, "session_delete", request)

    assert result.status == "ASK"
    assert result.exit_code == 4
    assert result.approval_required is True
    assert "approval" in result.reason.casefold()


def test_dry_run_reports_deny_for_missing_grant(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    WorkspaceAuthority(root).set_mode("security")
    request = ActionRequest(
        "session.resume", root.resolve(), "sessions", {"operation": "list"},
        execution_owner="chat_sessions",
    )

    result = preview_request(root, "chat_sessions", request)

    assert result.status == "DENY"
    assert result.exit_code == 3
    assert result.grant_id == ""
