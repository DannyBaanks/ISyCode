import asyncio
from isycode.tui import TUIApp, SidePanel, plain_text
from isycode import reasoning_options as reasoning
from isycode.providers import Provider
from test_daily_tui import configure


def test_effort_shortcuts_update_live_heading_boundaries_and_next_provider(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    monkeypatch.setenv("ISYCODE_MODEL", "z-ai/glm-5.3")
    monkeypatch.setattr(reasoning, "_SELECTIONS", {})
    monkeypatch.setattr(reasoning, "_CATALOG", {})
    reasoning.record_catalog("nvidia", "z-ai/glm-5.3", {"supportedReasoningEfforts": [
        {"reasoningEffort": "high"}, {"reasoningEffort": "low"}, {"reasoningEffort": "medium"}]})
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            assert not app.query_one(SidePanel).display
            for key, expected in [("alt+period", "Low"), ("alt+plus", "Medium"), ("alt+period", "High"),
                                  ("alt+period", "High"), ("alt+comma", "Medium"), ("alt+minus", "Low")]:
                await pilot.press(key)
                await pilot.pause()
                assert "GLM 5.3 / " + expected + " · NVIDIA NIM" in plain_text(app.query_one("#idea-box"))
                assert Provider(name="nvidia", model="z-ai/glm-5.3", api_key="fixture").reasoning_effort == expected.lower()
            await pilot.press("ctrl+b")
            await pilot.pause()
            assert app.query_one(SidePanel).display
    asyncio.run(scenario())


def test_unknown_effort_does_not_invent_levels(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    monkeypatch.setenv("ISYCODE_MODEL", "unknown-model")
    monkeypatch.setattr(reasoning, "_SELECTIONS", {})
    async def scenario():
        app = TUIApp()
        async with app.run_test() as pilot:
            await pilot.press("alt+period", "alt+comma")
            assert not reasoning._SELECTIONS
    asyncio.run(scenario())


def test_scroll_indicator_uses_same_stroke_in_both_directions(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            bar = app.query_one("#chat").vertical_scrollbar
            patterns = []
            for direction in (-1, 1):
                bar._direction = direction
                rows = [line.strip() for line in bar.render().plain.splitlines() if line.strip()]
                patterns.append(rows)
                assert rows == ["▲", "━━━", "▼"]
            assert patterns[0] == patterns[1]
            bar._settle()
            assert [line.strip() for line in bar.render().plain.splitlines() if line.strip()] == patterns[0]
    asyncio.run(scenario())
