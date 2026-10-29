"""Multi Harness: composing a repair reaches its confirmation dialog."""
import asyncio

import isycode.tui_app_sessions as sessions
from isycode.tui import TUIApp
from isycode.tui_screens_harness import HarnessRepairConfirmScreen


class _GapScreen:
    def __init__(self, *args, **kwargs):
        pass

    def update_snapshot(self, *args):
        pass

    def _gap_rows(self):
        return [{"semantic_id": "model.default", "harnesses": ["claude", "codex"]}]


def test_compose_branch_opens_repair_confirmation_and_launches_a_lane(monkeypatch):
    monkeypatch.setattr(sessions, "MultiHarnessScreen", _GapScreen)
    monkeypatch.setattr("isycode.harness_graph.repair_compose", lambda *args: "brief")
    monkeypatch.setattr("isycode.harness_graph.repair_targets", lambda rows: ["claude:settings.json"])
    shown, launched = [], []
    answers = iter(["compose:model.default", "lane", None])

    async def await_screen(self, screen):
        shown.append(screen)
        return next(answers)

    async def snapshot(self):
        return [], 0

    async def launch(self, brief):
        launched.append(brief)

    monkeypatch.setattr(TUIApp, "_await_screen", await_screen)
    monkeypatch.setattr(TUIApp, "_multi_harness_snapshot", snapshot)
    monkeypatch.setattr(TUIApp, "_launch_repair_conversation", launch)
    app = TUIApp.__new__(TUIApp)

    asyncio.run(TUIApp._show_multi_harness(app))

    assert isinstance(shown[1], HarnessRepairConfirmScreen)
    assert launched == ["brief"]
