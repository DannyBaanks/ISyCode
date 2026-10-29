import asyncio
from isycode.tui import TUIApp
from isycode.capability_observations import record
from test_daily_tui import configure

def test_unavailable_models_are_hidden_but_can_be_restored(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._account_model_catalogs = {"nvidia": [app._entry("Retired fixture", "model", "nvidia|retired-fixture"), app._entry("Unknown fixture", "model", "nvidia|unknown-fixture")]}
            record("nvidia", "retired-fixture", "chat_available", False)
            entries = app._branch_entries("models")
            assert not any(row["kind"] == "model" and row["value"] == "nvidia|retired-fixture" for row in entries)
            assert any(row["value"] == "nvidia|unknown-fixture" for row in entries)
            assert any("unavailable in tested endpoint" in row["label"] for row in entries)
            assert len(app._account_model_catalogs["nvidia"]) == 2
            record("nvidia", "retired-fixture", "chat_available", True)
            assert any(row["value"] == "nvidia|retired-fixture" for row in app._branch_entries("models"))
    asyncio.run(scenario())
