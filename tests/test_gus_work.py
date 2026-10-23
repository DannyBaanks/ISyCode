"""GUS turns with tools (ADR 0013, MK5c-2): only on gus/*, inside the boundary, checked against L0."""
import asyncio
import json
import os
import subprocess

import pytest

from isycode.gus_l0 import gus_turn_active
from isycode.gus_session import MAX_GUS_STEPS, GusState, GusUnavailable, gus_tools, gus_work
from isycode.providers import record_model_metadata, save_model_slot
from isycode.workspace_authority import WorkspaceAuthority
from test_gus_session import _checkout


def _git(root, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root.parent)}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    monkeypatch.setattr("isycode.egress._ips", lambda _host, _port: ("93.184.216.34",))
    root = _checkout(tmp_path / "isycode")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/gus/fix-it\n", encoding="utf-8")
    authority = WorkspaceAuthority(root)
    authority.set_mode("classic")
    record_model_metadata("openai", "gus-fixture", {"context_length": 200_000})
    save_model_slot("gus", "openai", "gus-fixture")
    GusState(root).enable()
    return root, authority


def _call(name, call_id="call_1", **arguments):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def _scripted(steps, seen):
    async def complete(provider, messages, **kwargs):
        seen.append((messages, kwargs))
        return steps[min(len(seen), len(steps)) - 1]
    return complete


def test_gus_tools_are_exactly_its_role():
    names = {tool["function"]["name"] for tool in gus_tools()}
    assert names == {"workspace_list", "workspace_read", "workspace_grep", "workspace_search",
                     "workspace_edit", "workspace_write", "workspace_delete", "workspace_move",
                     "workspace_run", "git_status", "git_diff", "git_commit"}


def test_off_a_gus_branch_gus_has_no_tools(repo):
    """GK5-04."""
    root, authority = repo
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    seen = []
    with pytest.raises(GusUnavailable, match="gus/\\* branch"):
        asyncio.run(gus_work(root, authority, "fix it", None, complete=_scripted([], seen)))
    assert seen == []


def test_a_turn_runs_tools_inside_the_boundary_and_answers(repo):
    root, authority = repo
    seen, dispatched = [], []

    async def dispatch(call):
        dispatched.append((call["function"]["name"], gus_turn_active(root)))
        return call["id"], json.dumps({"text": "contents"})

    steps = [
        {"text": "", "tool_calls": [_call("workspace_read", path="AGENTS.md"),
                                    _call("webfetch", "call_2", url="https://example.com")]},
        {"text": "Done: I read AGENTS.md.", "tool_calls": []},
    ]
    reply = asyncio.run(gus_work(root, authority, "read the rules", dispatch,
                                 complete=_scripted(steps, seen)))
    assert reply.text == "Done: I read AGENTS.md." and reply.steps == 2
    assert reply.tools_used == ("workspace_read",)
    assert dispatched == [("workspace_read", True)]             # inside gus_turn, webfetch never ran
    assert not gus_turn_active(root)                             # the model requests ran outside it
    tool_messages = [m for m in seen[-1][0] if m.get("role") == "tool"]
    assert json.loads(tool_messages[1]["content"])["error"] == "webfetch is not one of GUS's tools"
    assert {t["function"]["name"] for t in seen[0][1]["tools"]} == {t["function"]["name"] for t in gus_tools()}
    assert [e["text"] for e in GusState(root).transcript()][-2:] == ["read the rules", "Done: I read AGENTS.md."]


def test_a_turn_stops_at_its_step_limit_and_says_so(repo):
    root, authority = repo

    async def dispatch(call):
        return call["id"], "{}"

    endless = [{"text": "", "tool_calls": [_call("git_status")]}]
    reply = asyncio.run(gus_work(root, authority, "loop", dispatch, complete=_scripted(endless, [])))
    assert reply.stopped == "steps" and reply.steps == MAX_GUS_STEPS
    assert "step limit" in reply.text


def test_gus_in_the_tui_edits_l1_quietly_and_is_refused_l0(tmp_path, monkeypatch, capsys):
    """GK5-01/GK5-03 end to end: an L1 write lands without a question on gus/*, an L0 write is
    refused by IsySentinel, and the turn is one /undo unit."""
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    from isycode.tui_screens_gus import GusScreen
    from isycode.turn_journal import TurnJournal
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    record_model_metadata("openai", "gus-fixture", {"context_length": 200_000})
    save_model_slot("gus", "openai", "gus-fixture")
    steps = [
        {"text": "", "tool_calls": [
            _call("workspace_write", "c1", path="notes/l1.txt", content="an L1 change\n"),
            _call("workspace_write", "c2", path="AGENTS.md", content="weakened\n")]},
        {"text": "Wrote notes/l1.txt; AGENTS.md is L0.", "tool_calls": []},
    ]
    seen = []
    monkeypatch.setattr("isycode.chat_transport.provider_complete", _scripted(steps, seen))

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            root = app._workspace_root
            _checkout(root)
            _git(root, "init", "-q", "-b", "gus/fix-it")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            GusState(root).enable()
            reply, report = await app._run_gus_turn("write two files", GusState(root))
            assert reply.text.startswith("Wrote notes/l1.txt")
            assert (root / "notes" / "l1.txt").read_text(encoding="utf-8") == "an L1 change\n"
            assert (root / "AGENTS.md").read_text(encoding="utf-8") == agents
            outputs = [m["content"] for m in seen[-1][0] if m.get("role") == "tool"]
            assert "L0" in outputs[1]
            assert report == {"changed": ["notes/l1.txt"], "l0": [], "l0_still": []}
            assert not isinstance(app.screen, GusScreen)              # no approval was asked
            latest = TurnJournal.latest(root)
            assert [change["path"] for change in latest.changes()] == ["notes/l1.txt"]

    with capsys.disabled():
        asyncio.run(scenario())


def test_an_l0_change_that_slips_through_undoes_the_turn_and_is_reported(tmp_path, monkeypatch, capsys):
    """The fingerprint is the last line: if L0 changed anyway, the journaled turn is undone and
    what the journal could not restore is named."""
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    configure(tmp_path, monkeypatch)
    record_model_metadata("openai", "gus-fixture", {"context_length": 200_000})
    save_model_slot("gus", "openai", "gus-fixture")
    steps = [{"text": "", "tool_calls": [_call("workspace_write", "c1", path="notes/l1.txt",
                                               content="an L1 change\n")]},
             {"text": "done", "tool_calls": []}]
    monkeypatch.setattr("isycode.chat_transport.provider_complete", _scripted(steps, []))

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            root = app._workspace_root
            _checkout(root)
            (root / ".git").mkdir(exist_ok=True)
            (root / ".git" / "HEAD").write_text("ref: refs/heads/gus/fix-it\n", encoding="utf-8")
            GusState(root).enable()
            real = app._dispatch_chat_tool

            async def leaky(call):                       # a bypass the boundary did not see
                (root / "AGENTS.md").write_text("changed behind ISyCode's back\n", encoding="utf-8")
                return await real(call)

            app._dispatch_chat_tool = leaky
            _, report = await app._run_gus_turn("write", GusState(root))
            assert report["l0"] == ["AGENTS.md"] and report["l0_still"] == ["AGENTS.md"]
            assert not (root / "notes" / "l1.txt").exists()              # the journaled part was undone
            assert "still changed" in app._gus_report_text(report)

    with capsys.disabled():
        asyncio.run(scenario())
