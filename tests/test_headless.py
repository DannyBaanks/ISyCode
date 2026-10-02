"""isycode -p: one answer, the same owners and journal, no approval-gated tools."""
import asyncio
import io
import json
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.headless import EXIT_DENIED, EXIT_OK, EXIT_USAGE, available_tools, main, run_headless
from isycode.launcher import main as launcher_main
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    for name in ("ISYCODE_BASE_URL", "ISYMOTRON_BASE_URL", "ISYCODE_MODEL", "ISYMOTRON_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("ANSWER = 42\n")
    return root.resolve()


def _names(tools):
    return {tool["function"]["name"] for tool in tools}


def test_only_approval_free_granted_tools_are_offered(workspace):
    authority = WorkspaceAuthority(workspace)
    assert available_tools(workspace, authority) == []
    authority.set_mode("classic")
    names = _names(available_tools(workspace, authority))
    assert {"workspace_read", "workspace_grep"} <= names
    assert not names & {"workspace_write", "workspace_edit", "workspace_run", "git_commit"}


def test_a_tool_round_trip_is_owned_and_journaled(workspace):
    WorkspaceAuthority(workspace).set_mode("classic")
    requests = []

    async def transport(messages, tools, on_chunk):
        requests.append((list(messages), tools))
        if len(requests) == 1:
            return {"text": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "workspace_read", "arguments": json.dumps({"path": "app.py"})}}]}
        on_chunk("content", "It is 42.")
        return {"text": "It is 42.", "tool_calls": []}

    out, log = io.StringIO(), io.StringIO()
    code = asyncio.run(run_headless("What is ANSWER?", root=workspace, out=out, log=log,
                                    transport=transport))
    assert code == EXIT_OK and out.getvalue() == "It is 42.\n"
    assert "workspace_read ALLOW" in log.getvalue()
    tool_message = requests[1][0][-1]
    assert tool_message["role"] == "tool" and "ANSWER = 42" in tool_message["content"]
    # Two provider requests, credential use, and one workspace read are each
    # independently decided and receipted.
    report = ActionAuditJournal(workspace).verify()
    assert report.receipts == 4
    assert report.decisions == 4


def test_gated_tools_requested_by_the_model_are_refused(workspace):
    WorkspaceAuthority(workspace).set_mode("classic")
    calls = []

    async def transport(messages, tools, on_chunk):
        calls.append(messages[-1])
        if len(calls) == 1:
            return {"text": "", "tool_calls": [{"id": "c1", "function": {
                "name": "workspace_write", "arguments": json.dumps({"path": "x", "content": "y"})}}]}
        return {"text": "done", "tool_calls": []}

    out, log = io.StringIO(), io.StringIO()
    assert asyncio.run(run_headless("write", root=workspace, out=out, log=log,
                                    transport=transport, json_output=True)) == EXIT_OK
    assert "not available in non-interactive mode" in calls[1]["content"]
    assert not (workspace / "x").exists()
    result = json.loads(out.getvalue())
    assert result["answer"] == "done" and len(result["provider_receipts"]) == 2


def test_without_a_provider_grant_nothing_is_sent(workspace):
    async def transport(messages, tools, on_chunk):
        raise AssertionError("no request may be sent")

    log = io.StringIO()
    code = asyncio.run(run_headless("hi", root=workspace, out=io.StringIO(), log=log,
                                    transport=transport))
    assert code == EXIT_DENIED and "provider request DENY" in log.getvalue()


def test_usage_errors_and_launcher_routing(monkeypatch):
    assert main(["--json"]) == EXIT_USAGE
    assert main(["-p"], stdin=io.StringIO("   ")) == EXIT_USAGE
    seen = []
    monkeypatch.setattr("isycode.headless.main", lambda arguments: seen.append(arguments) or 0)
    assert launcher_main(["-p", "hello"]) == 0 and launcher_main(["--json", "-p", "x"]) == 0
    assert seen == [["-p", "hello"], ["--json", "-p", "x"]]
