import asyncio

from isycode.tui import TUIApp
from isycode.user_defaults import UserDefaultsStore
from test_daily_tui import configure


def test_operational_events_stay_out_of_the_transcript_and_show_on_demand(
        tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await app.wait_for_ready()
            await pilot.pause()
            lane = app._foreground_lane()
            before = list(lane.lines)
            app._append("Conversation unavailable · conversation was not found", log_only=True)
            assert lane.lines == before
            assert lane.operational_log[-1][1] == (
                "Conversation unavailable · conversation was not found")
            app._show_operational_log()
            await pilot.pause()
            assert any("Conversation unavailable" in str(line)
                       for line in lane.lines)
            assert any("Operational log · last 1 events" in str(line)
                       for line in lane.lines)

    with capsys.disabled():
        asyncio.run(scenario())


def test_missing_session_delete_is_logged_without_becoming_chat_text(
        tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await app.wait_for_ready()
            await pilot.pause()
            lane = app._foreground_lane()
            before = list(lane.lines)
            await app._delete_chat_session("missing-session", allow_once=True)
            await pilot.pause()
            assert lane.lines == before
            assert any("Conversation unavailable" in text
                       for _timestamp, text in lane.operational_log)

    with capsys.disabled():
        asyncio.run(scenario())


def test_returned_steering_is_logged_not_appended(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await app.wait_for_ready()
            await pilot.pause()
            lane = app._foreground_lane()
            before = list(lane.lines)
            app._return_steering_to_queue(["keep this"])
            await pilot.pause()
            assert lane.lines == before
            assert app._queued_messages == ["keep this"]
            assert any("Steer no confirmado" in text
                       for _timestamp, text in lane.operational_log)

    with capsys.disabled():
        asyncio.run(scenario())


def test_operational_log_is_bounded(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await app.wait_for_ready()
            await pilot.pause()
            lane = app._foreground_lane()
            for index in range(250):
                app._append(f"event {index}", log_only=True)
            assert len(lane.operational_log) == 200
            assert lane.operational_log[0][1] == "event 50"
            assert lane.operational_log[-1][1] == "event 249"

    with capsys.disabled():
        asyncio.run(scenario())
