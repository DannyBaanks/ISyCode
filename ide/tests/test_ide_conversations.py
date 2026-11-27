import asyncio
import json

from core.conversations import ConversationStore
from core.agent.chat import IsycoAgentApp
from core.ide_state import migrate_provider_metadata, migrate_project_metadata


def test_tui_history_reopens_and_clear_starts_another_conversation(tmp_path):
    store = ConversationStore(tmp_path)
    session = store.create()
    turn = store.begin(session, "saved request", "fixture", "model", "openai")
    store.append_response(session, turn, "saved reply")
    store.finish(turn, "completed")
    async def run():
        app = IsycoAgentApp(working_dir=str(tmp_path))
        async with app.run_test() as pilot:
            assert app.conversation_id == session
            assert len(app.chat_log.lines) > 1
            await app.handle_command("/clear")
            assert app.conversation_id is None
            await app.handle_command("/resume " + session)
            assert app.conversation_id == session
            app.running = True
            await app.handle_command("/clear")
            assert app.conversation_id == session
            app.running = False
            await app.handle_command("/sessions")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ConversationsModal"
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen.__class__.__name__ != "ConversationsModal"
    asyncio.run(run())


def test_provider_migration_is_additive_idempotent_and_preserves_source(tmp_path):
    import yaml
    source = tmp_path / "legacy.yaml"
    source.write_text(yaml.safe_dump({"providers": {"local": {"provider": "ollama", "model": "fixture", "api_key": "must-not-copy"}}}))
    original = source.read_bytes()
    target = tmp_path / "new/config.yaml"
    first = migrate_provider_metadata(source, target)
    assert first["imported"] == ["local"]
    assert "must-not-copy" not in target.read_text()
    assert migrate_provider_metadata(source, target)["imported"] == []
    saved = yaml.safe_load(target.read_text())
    saved["providers"]["local"]["model"] = "other"
    target.write_text(yaml.safe_dump(saved))
    before = target.read_bytes()
    assert migrate_provider_metadata(source, target)["conflicts"] == ["local"]
    assert target.read_bytes() == before and source.read_bytes() == original


def test_project_migration_retains_old_files_and_conflicts(tmp_path):
    legacy = tmp_path / ".isyvm"
    legacy.mkdir()
    (legacy / "mode.json").write_text(json.dumps({"mode": "coder"}))
    original = (legacy / "mode.json").read_bytes()
    result = migrate_project_metadata(tmp_path)
    assert result["imported"]
    target = tmp_path / ".isycode-ide/mode.json"
    assert target.read_bytes() == original
    assert migrate_project_metadata(tmp_path)["imported"] == []
    target.write_text(json.dumps({"mode": "plan"}))
    assert migrate_project_metadata(tmp_path)["conflicts"]
    assert (legacy / "mode.json").read_bytes() == original
