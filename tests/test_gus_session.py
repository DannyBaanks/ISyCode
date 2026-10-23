"""GUS conversations (ADR 0011, MK4): explicit enablement, own transcript, receipted requests."""
import asyncio
import shutil
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.gus_context_pack import PACK_FILES
from isycode.gus_session import MAX_TRANSCRIPT_ENTRIES, GusState, GusUnavailable, gus_reply
from isycode.providers import record_model_metadata, save_model_slot
from isycode.workspace_authority import WorkspaceAuthority

REPO = Path(__file__).resolve().parents[1]
MARKERS = ("src/isycode/gus_role.py", "src/isycode/agents/gus.md")


def _checkout(root: Path) -> Path:
    for relative in PACK_FILES + MARKERS:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, root / relative)
    shutil.copytree(REPO / "docs" / "decisions", root / "docs" / "decisions")
    return root.resolve()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    monkeypatch.setattr("isycode.egress._ips", lambda _host, _port: ("93.184.216.34",))
    root = _checkout(tmp_path / "isycode")
    authority = WorkspaceAuthority(root)
    authority.set_mode("classic")
    record_model_metadata("openai", "gus-fixture", {"context_length": 200_000})
    save_model_slot("gus", "openai", "gus-fixture")
    return root, authority


def _model(seen):
    async def complete(provider, messages, **kwargs):
        seen.append((provider, messages, kwargs))
        return {"text": f"answer {len(seen)}", "tool_calls": []}
    return complete


def test_gus_does_not_answer_until_the_person_enables_it_here(repo):
    """GK4-00."""
    root, authority = repo
    seen = []
    with pytest.raises(GusUnavailable, match="not enabled"):
        asyncio.run(gus_reply(root, authority, "hola", complete=_model(seen)))
    assert seen == []
    GusState(root).enable()
    reply = asyncio.run(gus_reply(root, authority, "hola", complete=_model(seen)))
    assert reply.text == "answer 1" and reply.model == "gus-fixture" and reply.window_known


def test_enabling_one_checkout_does_not_enable_a_copy(repo, tmp_path):
    root, _ = repo
    GusState(root).enable()
    copy = _checkout(tmp_path / "elsewhere")
    assert GusState(root).enabled()
    assert not GusState(copy).enabled()
    GusState(root).disable()
    assert not GusState(root).enabled()


def test_marker_files_alone_are_not_the_isycode_repo_check_bypass(repo, tmp_path):
    root, authority = repo
    GusState(root).enable()
    for marker in MARKERS:
        (root / marker).unlink()
    with pytest.raises(GusUnavailable, match="only in the ISyCode repository"):
        asyncio.run(gus_reply(root, authority, "hola", complete=_model([])))


def test_a_turn_sends_role_pack_and_transcript_through_the_receipted_owner(repo):
    root, authority = repo
    state = GusState(root)
    state.enable()
    seen = []
    asyncio.run(gus_reply(root, authority, "first", complete=_model(seen)))
    before = ActionAuditJournal(root).verify().receipts
    reply = asyncio.run(gus_reply(root, authority, "second", complete=_model(seen)))
    provider, messages, kwargs = seen[-1]
    assert provider.name == "openai" and provider.model == "gus-fixture"
    assert kwargs["tools"] is None                     # no tools before MK5
    assert messages[0]["content"].startswith("You are GUS")
    assert messages[1]["content"].startswith("ISyCode project context for GUS")
    assert [m["content"] for m in messages[2:]] == ["first", "answer 1", "second"]
    assert reply.receipt_id.startswith("rcpt_")
    assert ActionAuditJournal(root).verify().receipts > before
    assert [entry["text"] for entry in state.transcript()] == ["first", "answer 1", "second", "answer 2"]


def test_the_transcript_is_separate_and_bounded(repo):
    root, _ = repo
    state = GusState(root)
    for index in range(MAX_TRANSCRIPT_ENTRIES + 10):
        state.append("user", f"m{index}")
    entries = state.transcript()
    assert len(entries) == MAX_TRANSCRIPT_ENTRIES and entries[-1]["text"] == f"m{MAX_TRANSCRIPT_ENTRIES + 9}"
    state.clear()
    assert state.transcript() == []


def test_without_a_model_gus_says_so_instead_of_using_the_chat_model(repo):
    root, authority = repo
    GusState(root).enable()
    save_model_slot("gus", "openai", "tiny")
    record_model_metadata("openai", "tiny", {"context_length": 8_192})
    with pytest.raises(GusUnavailable, match="below 32k"):
        asyncio.run(gus_reply(root, authority, "hola", complete=_model([])))


def test_without_a_read_grant_gus_has_no_fixed_context(repo):
    root, authority = repo
    GusState(root).enable()
    authority.set_mode("security")
    with pytest.raises(GusUnavailable, match="could not be read"):
        asyncio.run(gus_reply(root, authority, "hola", complete=_model([])))


def test_an_unknown_window_is_budgeted_as_32k(repo, monkeypatch):
    """GK4-03."""
    root, authority = repo
    GusState(root).enable()
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    save_model_slot("gus", "ollama", "qwen3:32b")
    seen = []
    monkeypatch.setattr("isycode.egress._ips", lambda _host, _port: ("127.0.0.1",))
    state = GusState(root)
    for index in range(60):                       # a long earlier conversation
        state.append("user", f"question {index} " + "q" * 3_000)
        state.append("assistant", f"answer {index} " + "a" * 3_000)
    reply = asyncio.run(gus_reply(root, authority, "next", complete=_model(seen)))
    assert not reply.window_known
    used = sum(len(str(m["content"])) for m in seen[-1][1])
    assert used <= 32_000 * 3 * 0.75
    with pytest.raises(GusUnavailable, match="too large"):
        asyncio.run(gus_reply(root, authority, "x" * 200_000, complete=_model(seen)))
    assert len(seen) == 1                          # the oversized message was never sent


def test_gus_in_the_tui_asks_once_then_talks_in_its_own_window(tmp_path, monkeypatch, capsys):
    """GK4-00/GK4-01: /gus outside the repo refuses, inside asks to enable, then talks."""
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    from isycode.tui_screens_approval import TailscaleConfirmScreen
    from isycode.tui_screens_gus import GusScreen
    configure(tmp_path, monkeypatch)
    record_model_metadata("openai", "gus-fixture", {"context_length": 200_000})
    save_model_slot("gus", "openai", "gus-fixture")
    seen = []
    monkeypatch.setattr("isycode.chat_transport.provider_complete", _model(seen))

    async def until(pilot, condition, what):
        # Startup work shares the event loop; a loaded full-suite run needs room.
        for _ in range(200):
            if condition():
                return
            await pilot.pause(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    async def scenario():
        app = TUIApp()
        notes = []
        set_activity = app._set_activity
        app._set_activity = lambda text, *args, **kwargs: (notes.append(str(text)),
                                                           set_activity(text, *args, **kwargs))
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            await app._open_gus("hola")
            # Startup can repaint the activity line later; check what GUS reported.
            assert any("only in the ISyCode repository" in note for note in notes)
            assert not isinstance(app.screen, GusScreen)
            _checkout(app._workspace_root)

            task = asyncio.ensure_future(app._open_gus())
            await until(pilot, lambda: isinstance(app.screen, TailscaleConfirmScreen), "the enable prompt")
            app.screen.dismiss(False)                      # declined: nothing enabled
            await task
            assert not GusState(app._workspace_root).enabled()

            task = asyncio.ensure_future(app._open_gus("hola GUS"))
            await until(pilot, lambda: isinstance(app.screen, TailscaleConfirmScreen), "the enable prompt")
            app.screen.dismiss(True)
            await until(pilot, lambda: isinstance(app.screen, GusScreen)
                        and len(app.screen.query(".gus-line")) >= 2, "GUS's answer")
            screen = app.screen
            assert isinstance(screen, GusScreen)
            assert screen.focused is screen.query_one("#gus-input")   # never the Clear button
            assert GusState(app._workspace_root).enabled()
            lines = [str(line.render()) for line in screen.query(".gus-line")]
            assert "hola GUS" in lines[0] and lines[1].startswith("GUS · answer 1")
            assert seen[-1][2]["tools"] is None
            assert all(message.get("content") != "hola GUS" for message in app._history)
            screen.dismiss_action("gus-clear")
            await pilot.pause()
            assert GusState(app._workspace_root).transcript() == []
            screen.dismiss(None)
            await task

            await app._toggle_gus_here()                   # Settings switch turns it off
            assert not GusState(app._workspace_root).enabled()
            assert "gus_toggle" in [entry["kind"] for entry in app._menu_entries]

    with capsys.disabled():
        asyncio.run(scenario())
