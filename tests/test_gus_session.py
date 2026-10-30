"""GUS conversations (ADR 0011, ADR 0015): enablement, three roots, own transcript, receipts."""
import asyncio
import shutil
from pathlib import Path

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.gus_context_pack import PACK_FILES, ContextPackError, ContextPackReader
from isycode.gus_roots import GusRoots, GusSettingsStore
from isycode.gus_memory import MAX_CONVERSATION_ENTRIES
from isycode.gus_session import GusState, GusUnavailable, gus_reply
from isycode.providers import record_model_metadata, save_model_slot

REPO = Path(__file__).resolve().parents[1]
MARKERS = ("src/isycode/gus_role.py", "src/isycode/agents/gus.md")


def _checkout(root: Path) -> Path:
    for relative in PACK_FILES + MARKERS:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, root / relative)
    shutil.copytree(REPO / "docs" / "decisions", root / "docs" / "decisions")
    return root.resolve()


def _target(root: Path) -> Path:
    store = GusSettingsStore()
    data = store.read()
    data["target"] = str(root)
    store.write(data)
    return root


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    monkeypatch.setattr("isycode.egress._ips", lambda _host, _port: ("93.184.216.34",))
    root = _target(_checkout(tmp_path / "isycode"))
    record_model_metadata("openai", "gus-fixture", {"context_length": 200_000})
    save_model_slot("gus", "openai", "gus-fixture")
    return root


def _model(seen):
    async def complete(provider, messages, **kwargs):
        seen.append((provider, messages, kwargs))
        return {"text": f"answer {len(seen)}", "tool_calls": []}
    return complete


def test_gus_does_not_answer_until_the_person_enables_it_here(repo):
    """GK4-00."""
    roots = GusRoots(repo)
    seen = []
    with pytest.raises(GusUnavailable, match="not enabled"):
        asyncio.run(gus_reply(roots, "hola", complete=_model(seen)))
    assert seen == []
    GusState(repo).enable()
    reply = asyncio.run(gus_reply(roots, "hola", complete=_model(seen)))
    assert reply.text == "answer 1" and reply.model == "gus-fixture" and reply.window_known


def test_enabling_one_workspace_does_not_enable_another(repo, tmp_path):
    GusState(repo).enable()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert GusState(repo).enabled()
    assert not GusState(elsewhere).enabled()
    GusState(repo).disable()
    assert not GusState(repo).enabled()


def test_gus_talks_in_a_workspace_that_is_not_a_checkout(repo, tmp_path):
    """ADR 0015: the conversation no longer requires an ISyCode checkout."""
    plain = tmp_path / "plain"
    plain.mkdir()
    roots = GusRoots(plain)
    assert roots.target == repo                       # edits still go to the target
    GusState(plain).enable()
    seen = []
    reply = asyncio.run(gus_reply(roots, "hola", complete=_model(seen)))
    assert reply.text == "answer 1"
    assert seen[-1][1][1]["content"].startswith("ISyCode project context for GUS")


def test_a_turn_sends_role_pack_and_transcript_through_the_receipted_owner(repo):
    state = GusState(repo)
    state.enable()
    roots = GusRoots(repo)
    seen = []
    asyncio.run(gus_reply(roots, "first", complete=_model(seen)))
    before = ActionAuditJournal(repo).verify().receipts
    reply = asyncio.run(gus_reply(roots, "second", complete=_model(seen)))
    provider, messages, kwargs = seen[-1]
    assert provider.name == "openai" and provider.model == "gus-fixture"
    assert kwargs["tools"] is None                     # no tools before MK5
    assert messages[0]["content"].startswith("You are GUS")
    assert messages[1]["content"].startswith("ISyCode project context for GUS")
    assert [m["content"] for m in messages[2:]] == ["first", "answer 1", "second"]
    assert reply.receipt_id.startswith("rcpt_")
    assert ActionAuditJournal(repo).verify().receipts > before
    assert [entry["text"] for entry in state.transcript()] == ["first", "answer 1", "second", "answer 2"]


def test_the_transcript_is_separate_and_bounded(repo):
    state = GusState(repo)
    for index in range(MAX_CONVERSATION_ENTRIES + 10):
        state.append("user", f"m{index}")
    entries = state.transcript()
    assert len(entries) == MAX_CONVERSATION_ENTRIES and entries[-1]["text"] == f"m{MAX_CONVERSATION_ENTRIES + 9}"
    state.clear()
    assert state.transcript() == []


def test_without_a_model_gus_says_so_instead_of_using_the_chat_model(repo):
    GusState(repo).enable()
    save_model_slot("gus", "openai", "tiny")
    record_model_metadata("openai", "tiny", {"context_length": 8_192})
    with pytest.raises(GusUnavailable, match="below 32k"):
        asyncio.run(gus_reply(GusRoots(repo), "hola", complete=_model([])))


def test_a_target_that_cannot_be_read_still_answers_with_the_roots_pack(repo, monkeypatch):
    GusState(repo).enable()
    seen = []

    def unreadable(self, roots_section=""):
        raise ContextPackError("the target cannot be read")

    monkeypatch.setattr(ContextPackReader, "build", unreadable)
    reply = asyncio.run(gus_reply(GusRoots(repo), "hola", complete=_model(seen)))
    assert reply.text == "answer 1"
    assert "GUS roots" in seen[-1][1][1]["content"]


def test_an_unknown_window_is_budgeted_as_32k(repo, monkeypatch):
    """GK4-03."""
    GusState(repo).enable()
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    save_model_slot("gus", "ollama", "qwen3:32b")
    seen = []
    monkeypatch.setattr("isycode.egress._ips", lambda _host, _port: ("127.0.0.1",))
    state = GusState(repo)
    for index in range(60):                       # a long earlier conversation
        state.append("user", f"question {index} " + "q" * 3_000)
        state.append("assistant", f"answer {index} " + "a" * 3_000)
    roots = GusRoots(repo)
    reply = asyncio.run(gus_reply(roots, "next", complete=_model(seen)))
    assert not reply.window_known
    used = sum(len(str(m["content"])) for m in seen[-1][1])
    assert used <= 32_000 * 3 * 0.75
    with pytest.raises(GusUnavailable, match="too large"):
        asyncio.run(gus_reply(roots, "x" * 200_000, complete=_model(seen)))
    assert len(seen) == 1                          # the oversized message was never sent


def test_gus_in_the_tui_asks_once_then_talks_in_its_own_window(tmp_path, monkeypatch, capsys):
    """GK4-00/GK4-01 + ADR 0015: the button is everywhere; GUS talks outside a checkout."""
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    from isycode.tui_screens_approval import ConfirmScreen
    from isycode.tui_screens_gus import GusScreen
    configure(tmp_path, monkeypatch)
    target = _target(_checkout(tmp_path / "gus-target"))
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
            assert app._workspace_root != target          # a plain workspace
            gus_button = app.query_one("#gus-button")
            assert gus_button.display                     # ADR 0015: never hidden by the root
            mode_button = app.query_one("#mode-button")
            assert gus_button.region.right <= mode_button.region.x  # just left of the mode chip

            declined = asyncio.ensure_future(app._open_gus("hola"))
            await until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "the enable prompt")
            app.screen.dismiss(False)
            await declined
            await pilot.pause()
            assert not GusState(app._workspace_root).enabled()
            assert not isinstance(app.screen, GusScreen)

            task = asyncio.ensure_future(app._open_gus("hola GUS"))
            await until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "the enable prompt")
            app.screen.dismiss(True)
            await until(pilot, lambda: isinstance(app.screen, GusScreen)
                        and len(app.screen.query(".gus-line")) >= 2, "GUS's answer")
            screen = app.screen
            assert isinstance(screen, GusScreen)
            assert screen.target == target
            assert screen.focused is screen.query_one("#gus-input")   # never the Clear button
            assert GusState(app._workspace_root).enabled()
            lines = [str(line.render()) for line in screen.query(".gus-line")]
            assert "hola GUS" in lines[0] and lines[1].startswith("GUS · answer 1")
            offered = {tool["function"]["name"] for tool in seen[-1][2]["tools"]}
            assert offered == {"memory_remember"}             # chat offers memory, no edits
            assert all(message.get("content") != "hola GUS" for message in app._history)
            screen.dismiss_action("gus-clear")
            await pilot.pause()
            assert GusState(app._workspace_root).transcript() == []
            screen.dismiss(None)
            await task

            await pilot.click("#gus-button")               # the bar button opens the same window
            await until(pilot, lambda: isinstance(app.screen, GusScreen), "GUS's window from the bar")
            app.screen.dismiss(None)
            await pilot.pause()

            await app._toggle_gus_here()                   # Settings switch turns it off
            assert not GusState(app._workspace_root).enabled()
            kinds = [entry["kind"] for entry in app._menu_entries]
            assert "gus_toggle" in kinds and "gus_settings" in kinds

    with capsys.disabled():
        asyncio.run(scenario())


def test_gus_window_and_settings_fit_80x24(tmp_path, monkeypatch, capsys):
    """ADR 0015: the GUS window and its settings form stay usable in a small terminal."""
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    from isycode.tui_screens_gus import GusScreen
    from isycode.tui_screens_gus_settings import GusSettingsScreen
    configure(tmp_path, monkeypatch)
    target = _target(_checkout(tmp_path / "gus-target"))
    record_model_metadata("openai", "gus-fixture", {"context_length": 200_000})
    save_model_slot("gus", "openai", "gus-fixture")
    seen = []
    monkeypatch.setattr("isycode.chat_transport.provider_complete", _model(seen))

    async def until(pilot, condition, what):
        for _ in range(200):
            if condition():
                return
            await pilot.pause(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.wait_for_ready()
            GusState(app._workspace_root).enable()
            task = asyncio.ensure_future(app._open_gus("hola"))
            await until(pilot, lambda: isinstance(app.screen, GusScreen)
                        and len(app.screen.query(".gus-line")) >= 2, "GUS's answer")
            screen = app.screen
            assert screen.size.width == 80 and screen.size.height == 24
            assert screen.query_one("#gus-input").region.width > 0
            note = str(screen.query_one(".isy-dialog-copy").render())
            assert str(target) in note and "80" not in note   # the target is named, no overflow copy
            screen.dismiss(None)
            await task
            await pilot.pause()

            settings_task = asyncio.ensure_future(app._open_gus_settings())
            await until(pilot, lambda: isinstance(app.screen, GusSettingsScreen), "the settings form")
            form = app.screen
            assert form.query_one("#gus-target-input").value == str(target)
            assert form.query_one("#gus-settings-save").region.width > 0
            form.dismiss(None)
            await settings_task

    with capsys.disabled():
        asyncio.run(scenario())
