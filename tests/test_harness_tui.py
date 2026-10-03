import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from isycode.harness_graph import CATALOG_IDS, HarnessSetting
from isycode.harness_probe import ProbeResult
from isycode.harness_readers.transcript import TranscriptCopy
from isycode.tui import (
    HarnessFolderConfirmScreen, HarnessModelConfirmScreen, HarnessTranscriptConfirmScreen,
    MultiHarnessScreen, TUIApp,
)
from test_daily_tui import configure


SOURCE = Path(__file__).resolve().parents[1] / "src" / "isycode" / "tui.py"


def test_multi_harness_is_reachable_from_bar_settings_and_slash(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            button = app.query_one("#harness-button")
            assert str(button.label) == "Multi Harness"
            app._open_settings_menu()
            assert any(entry["kind"] == "harness_open" for entry in app._menu_entries)
            _, command, _ = app._plugins.route("/harness")
            assert command is not None and command.name == "harness"

    with capsys.disabled():
        asyncio.run(scenario())


def test_multi_harness_button_opens_and_escape_closes_without_blocking_app(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()

        async def snapshot():
            return [], 0

        monkeypatch.setattr(app, "_multi_harness_snapshot", snapshot)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await asyncio.wait_for(pilot.click("#harness-button"), timeout=2)
            await pilot.pause()
            assert isinstance(app.screen, MultiHarnessScreen)
            assert len(app.screen.query(".harness-section")) == len(CATALOG_IDS)
            await asyncio.wait_for(pilot.press("escape"), timeout=2)
            await pilot.pause()
            assert not isinstance(app.screen, MultiHarnessScreen)
            await asyncio.wait_for(pilot.click("#harness-button"), timeout=2)
            await pilot.pause()
            assert isinstance(app.screen, MultiHarnessScreen)
            await asyncio.wait_for(pilot.click("#harness-close"), timeout=2)
            await pilot.pause()
            assert not isinstance(app.screen, MultiHarnessScreen)

    with capsys.disabled():
        asyncio.run(scenario())


def test_multi_harness_snapshot_uses_owner_count_and_catalog_order(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    app = TUIApp()
    probes = {
        harness_id: ProbeResult(harness_id, Path("/bin/true"), harness_id == "grok", "fake 1")
        for harness_id in CATALOG_IDS
    }

    async def fake_probe_catalog(*, timeout=3.0):
        return probes

    monkeypatch.setattr("isycode.tui.probe_catalog", fake_probe_catalog)
    monkeypatch.setattr(
        "isycode.tui.unlock_dotfolder",
        lambda result: root if result.harness_id == "grok" and result.answered else None,
    )
    monkeypatch.setattr(
        "isycode.tui.read_harness_root",
        lambda harness_id, path, automatic=True: ([
            HarnessSetting(
                harness_id=harness_id,
                relative_path="config.toml",
                pointer="ui.vim_mode",
                value_type="bool",
                semantic_id="vim_mode",
                edge="same",
                display_value="set",
            ),
            HarnessSetting(
                harness_id=harness_id,
                relative_path="config.toml",
                pointer="model.default",
                value_type="model-id",
                semantic_id="default_model",
                edge="same",
                display_value="gpt-test",
                provider_id="openai",
                model_id="gpt-test",
            ),
        ], []),
    )
    app._chat_session_owner = SimpleNamespace(
        list_conversations=lambda: (SimpleNamespace(decision="ALLOW", reason=""), [object(), object()])
    )
    monkeypatch.setattr(app, "_sessions_enabled", lambda: True)

    sections, transcript_count = asyncio.run(app._multi_harness_snapshot())
    assert [section["harness_id"] for section in sections] == list(CATALOG_IDS)
    grok = next(section for section in sections if section["harness_id"] == "grok")
    assert grok["unlocked"] is True
    assert grok["settings"][0]["semantic_id"] == "vim_mode"
    assert grok["settings"][0]["n"] == 1
    assert grok["settings"][1]["copyable"] is False
    assert transcript_count == 2


def test_multi_harness_tui_keeps_processes_outside_tuiapp_and_lists_sessions_via_owner():
    source = SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    snapshot = ast.get_source_segment(source, methods["_multi_harness_snapshot"])
    assert "owner.list_conversations" in snapshot
    assert "ChatSessionStore" not in snapshot
    assert "list_sessions" not in snapshot

    forbidden_names = {"create_subprocess_exec", "Popen", "check_call", "check_output"}
    forbidden_subprocess_attrs = {"Popen", "run", "call", "check_call", "check_output"}
    for node in ast.walk(app):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_names
            elif isinstance(node.func, ast.Attribute):
                receiver = ast.get_source_segment(source, node.func.value) or ""
                assert not (
                    receiver in {"subprocess", "asyncio"}
                    and node.func.attr in forbidden_subprocess_attrs | {"create_subprocess_exec"}
                )


def test_multi_harness_picked_root_unlocks_only_selected_harness(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    picked = tmp_path / "picked-opencode"
    picked.mkdir()
    app = TUIApp()
    probes = {
        harness_id: ProbeResult(harness_id, None, False, "")
        for harness_id in CATALOG_IDS
    }

    async def fake_probe_catalog(*, timeout=3.0):
        return probes

    monkeypatch.setattr("isycode.tui.probe_catalog", fake_probe_catalog)
    monkeypatch.setattr("isycode.tui.unlock_dotfolder", lambda result: None)
    store = SimpleNamespace(roots=lambda: {"opencode": picked})
    monkeypatch.setattr(app, "_harness_store", lambda: store)
    monkeypatch.setattr(
        "isycode.tui.read_harness_root",
        lambda harness_id, path, automatic=True: ([HarnessSetting(
            harness_id=harness_id,
            relative_path="opencode.jsonc",
            pointer="plugin[]",
            value_type="list",
            semantic_id="enabled_plugins",
            edge="non_equivalent",
            display_value="1 plugin entry",
            counts_toward_n=False,
        )], []),
    )
    monkeypatch.setattr(app, "_sessions_enabled", lambda: False)

    sections, _ = asyncio.run(app._multi_harness_snapshot())
    opencode = next(section for section in sections if section["harness_id"] == "opencode")
    assert opencode["unlocked"] is True
    assert opencode["automatic"] is False
    assert opencode["root"] == str(picked)
    assert all(not section["unlocked"] for section in sections if section["harness_id"] != "opencode")


def test_multi_harness_choose_folder_validates_confirms_and_saves(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    picked = tmp_path / "picked"
    picked.mkdir()
    saved = []
    app = TUIApp()
    monkeypatch.setattr("isycode.tui.choose_harness_folder", lambda *args, **kwargs: asyncio.sleep(0, result=picked))
    monkeypatch.setattr("isycode.tui.validate_picked_root", lambda candidate: candidate.resolve())
    monkeypatch.setattr(app, "_await_screen", lambda screen: asyncio.sleep(0, result=isinstance(screen, HarnessFolderConfirmScreen)))
    monkeypatch.setattr(app, "_harness_store", lambda: SimpleNamespace(set_root=lambda harness_id, path: saved.append((harness_id, path))))
    monkeypatch.setattr(app, "_set_activity", lambda *args, **kwargs: None)

    assert asyncio.run(app._choose_harness_root("crush")) is True
    assert saved == [("crush", picked.resolve())]


def test_multi_harness_screen_has_choose_folder_action_for_every_harness():
    screen = MultiHarnessScreen()
    assert [section["harness_id"] for section in screen.sections] == list(CATALOG_IDS)
    assert screen._pick_button_id("crush") == "harness-pick-crush"


def test_multi_harness_gap_table_is_read_only_and_uses_threshold_four():
    screen = MultiHarnessScreen()
    sections = []
    memberships = {
        "user_skills": {"claude", "codex", "hermes", "openclaw"},
        "ui_theme": {"claude", "pi", "kimi"},
        "default_model": {"codex", "hermes", "fx", "openclaw", "kimi"},
        "provider_endpoint": {"codex", "hermes", "openclaw", "kimi"},
    }
    for harness_id in CATALOG_IDS:
        rows = []
        for semantic_id, harnesses in memberships.items():
            if harness_id in harnesses:
                rows.append({
                    "semantic_id": semantic_id,
                    "pointer": "fixture",
                    "edge": "same",
                    "display_value": "set",
                    "n": len(harnesses),
                    "counts_toward_n": True,
                })
        sections.append({
            "harness_id": harness_id,
            "checking": False,
            "unlocked": bool(rows),
            "settings": rows,
        })
    screen.sections = sections

    gaps = {row["semantic_id"]: row for row in screen._gap_rows()}
    assert gaps["user_skills"]["status"] == "ADD"
    assert gaps["user_skills"]["target_label"] == "Missing in ISyCode"
    assert gaps["user_skills"]["n"] == 4
    assert gaps["ui_theme"]["status"] == "WATCH"
    assert gaps["ui_theme"]["n"] == 3
    assert gaps["default_model"]["status"] == "ALIGNED"
    assert gaps["provider_endpoint"]["status"] == "DO_NOT_MERGE"
    assert gaps["provider_endpoint"]["copy_note"] == "will not be copied"
    assert gaps["web_fetch"]["status"] == "WATCH" and gaps["web_fetch"]["n"] == 0
    assert gaps["web_search"]["status"] == "WATCH" and gaps["web_search"]["n"] == 0
    assert "Missing in ISyCode" in screen._render_text()


def test_multi_harness_copy_button_only_for_guarded_default_model():
    screen = MultiHarnessScreen()
    screen.update_snapshot([
        {
            "harness_id": "fx", "checking": False, "unlocked": True,
            "settings": [{
                "semantic_id": "default_model", "pointer": "models.gateway",
                "edge": "same", "display_value": "gpt-5.6-sol", "n": 4,
                "counts_toward_n": True, "provider_id": "openai",
                "model_id": "gpt-5.6-sol", "copyable": True,
            }],
        },
        {
            "harness_id": "kimi", "checking": False, "unlocked": True,
            "settings": [{
                "semantic_id": "default_model", "pointer": "default_model",
                "edge": "same", "display_value": "kimi-test", "n": 4,
                "counts_toward_n": True, "provider_id": "managed:kimi-code",
                "model_id": "kimi-test", "copyable": False,
            }],
        },
    ], 0)
    assert screen.copyable_models == {"fx": ("openai", "gpt-5.6-sol")}
    assert screen._copy_button_id("fx") == "harness-copy-fx"


def test_multi_harness_copy_confirms_then_calls_narrow_helper(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    copied = []
    monkeypatch.setattr(
        app, "_await_screen",
        lambda screen: asyncio.sleep(0, result=isinstance(screen, HarnessModelConfirmScreen)),
    )
    monkeypatch.setattr(
        "isycode.tui.copy_default_model_selection",
        lambda provider, model: copied.append((provider, model)) or (provider, model),
    )
    monkeypatch.setattr(app, "_set_activity", lambda *args, **kwargs: None)

    assert asyncio.run(app._copy_harness_default_model("openai", "gpt-5.6-sol")) is True
    assert copied == [("openai", "gpt-5.6-sol")]


def test_multi_harness_transcript_button_only_for_reviewed_concrete_source():
    screen = MultiHarnessScreen()
    screen.update_snapshot([
        {
            "harness_id": "grok", "checking": False, "unlocked": True,
            "root": "/fixture/grok",
            "settings": [{
                "semantic_id": "prior_transcript", "pointer": "filename",
                "edge": "same", "display_value": "1 transcript file", "n": 1,
                "counts_toward_n": True,
            }],
            "transcript_sources": ["sessions/project/session/chat_history.jsonl"],
        },
        {
            "harness_id": "hermes", "checking": False, "unlocked": True,
            "root": "/fixture/hermes", "settings": [], "transcript_sources": [],
        },
    ], 0)
    assert screen.transcript_sources == {
        "grok": ("/fixture/grok", "sessions/project/session/chat_history.jsonl")
    }
    assert screen._transcript_button_id("grok") == "harness-transcript-grok"


def test_harness_transcript_import_refuses_while_another_reply_is_running(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()

    class Busy:
        def done(self):
            return False

    app._loop_task = Busy()
    called = []
    monkeypatch.setattr(app, "_await_screen", lambda screen: called.append(screen) or asyncio.sleep(0, result=True))

    assert asyncio.run(app._import_harness_transcript(
        "grok", tmp_path, "sessions/project/session/chat_history.jsonl")) is False
    assert called == []


def test_harness_transcript_confirm_reads_after_confirm_and_passes_inert_messages(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = TUIApp()
    seen = []
    copy = TranscriptCopy(({"role": "user", "content": "do not execute me"},), 1, 0)
    monkeypatch.setattr(
        app, "_await_screen",
        lambda screen: asyncio.sleep(0, result=isinstance(screen, HarnessTranscriptConfirmScreen)),
    )
    monkeypatch.setattr("isycode.tui.read_transcript", lambda root, relative: copy)

    async def apply(harness_id, transcript):
        seen.append((harness_id, transcript))
        return True

    monkeypatch.setattr(app, "_apply_harness_transcript", apply)
    assert asyncio.run(app._import_harness_transcript(
        "grok", tmp_path, "sessions/project/session/chat_history.jsonl")) is True
    assert seen == [("grok", copy)]


def test_harness_transcript_sessions_off_stays_in_history_and_paints(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "_sessions_enabled", lambda: False)
            app._chat_session_owner = None
            copy = TranscriptCopy((
                {"role": "user", "content": "foreign user text"},
                {"role": "assistant", "content": "foreign assistant text"},
            ), 2, 0)
            assert await app._apply_harness_transcript("grok", copy)
            assert app._history[0]["role"] == "user"
            assert "copy of text" in app._history[0]["content"]
            assert app._history[1:] == list(copy.messages)
            chat_text = "\n".join(app._render_searchable_text(node) for node in app.query_one("#chat").children)
            assert "foreign user text" in chat_text
            assert "foreign assistant text" in chat_text

    with capsys.disabled():
        asyncio.run(scenario())


def test_harness_transcript_persists_same_session_with_state_none_and_keeps_not_verifiable(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    class Owner:
        def __init__(self):
            self.calls = []

        def record(self, session_id, role, content, *, state=None):
            self.calls.append((session_id, role, content, state))
            if len(self.calls) == 3:
                return SimpleNamespace(decision="NOT_VERIFIABLE", reason="journal unavailable"), "sid-copy"
            return SimpleNamespace(decision="ALLOW", reason="ok"), "sid-copy"

        def manage(self, operation, session_id, data):
            return SimpleNamespace(decision="ALLOW", reason="ok"), session_id

    async def scenario():
        app = TUIApp()
        owner = Owner()
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            app._chat_session_owner = owner
            monkeypatch.setattr(app, "_sessions_enabled", lambda: True)
            copy = TranscriptCopy((
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "user", "content": "three must not be attempted"},
            ), 3, 0)
            assert not await app._apply_harness_transcript("grok", copy)
            assert owner.calls[0][0] is None
            assert owner.calls[1][0] == "sid-copy"
            assert owner.calls[2][0] == "sid-copy"
            assert all(call[3] is None for call in owner.calls)
            assert app._active_chat_session_id == "sid-copy"
            assert [item["content"] for item in app._history][-2:] == ["one", "two"]
            assert all("three must not be attempted" not in item["content"] for item in app._history)

    with capsys.disabled():
        asyncio.run(scenario())


def test_harness_transcript_import_never_reuses_session_state_or_chat_execution_paths():
    source = SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: node for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    segment = ast.get_source_segment(source, methods["_apply_harness_transcript"])
    assert "owner.record(" in segment
    assert "state=None" in segment
    for forbidden in ("_persist_chat_message", "_session_state", "_run_chat", "_dispatch_chat_tool"):
        assert forbidden not in segment
