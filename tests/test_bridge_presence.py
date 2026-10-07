"""Bridge presence is a reviewed name list, never a connection."""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from isycode.bridge_presence import parse_agents
from isycode.tui import TUIApp
from test_daily_tui import configure


def test_presence_parser_keeps_fresh_public_names_only():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(seconds=30)).isoformat()
    quiet = (now - timedelta(minutes=20)).isoformat()
    ancient = (now - timedelta(days=2)).isoformat()
    output = (
        "Agents registry (/tmp/agents.json):\n"
        f"  alpha            caps=[audit] last_hb={fresh} status=working\n"
        f"  beta             caps=[x] last_hb={quiet} status=alive\n"
        f"  delta            caps=[x] last_hb={ancient} status=alive\n"
        f"  gamma            caps=[x] last_hb={fresh} status=token=secret\n"
        f"  old              caps=[x] last_hb={fresh} status=stale\n"
    )
    assert parse_agents(output, now=now) == [
        {"name": "alpha", "status": "working", "heartbeat": fresh},
        {"name": "beta", "status": "alive", "heartbeat": quiet},
        {"name": "gamma", "status": "active", "heartbeat": fresh},
    ]
    rendered = str(parse_agents(output, now=now))
    assert "secret" not in rendered and "delta" not in rendered


def test_presence_button_never_reaches_bridge_client():
    source = Path(__file__).resolve().parents[1].joinpath("src", "isycode", "tui.py").read_text()
    module = ast.parse(source)
    app = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    methods = {node.name: ast.get_source_segment(source, node) for node in app.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    body = methods["_show_bridge_presence"]
    assert "_show_bridge_presence" in (methods["on_button_pressed"] or "")
    assert "BridgeClient" not in body
    assert "subprocess" not in body
    for banned in ("hello", "send", "claim", "wake", "peek"):
        assert f'"{banned}"' not in body and f"'{banned}'" not in body


def test_presence_button_lists_names_only_after_confirmation(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    calls = []
    fresh = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        class Result:
            returncode = 0
            stdout = f"Agents registry (fixture):\n  peer             caps=[read] last_hb={fresh} status=idle\n"
            stderr = ""
        return Result()

    monkeypatch.setattr("isycode.bridge_presence.subprocess.run", fake_run)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await app._show_chat_sessions()
            await pilot.pause()
            cancelled = asyncio.create_task(app._show_bridge_presence())
            await pilot.pause()
            assert app.screen.id == "bridge-presence"
            await pilot.press("escape")
            await cancelled
            assert calls == []
            shown = asyncio.create_task(app._show_bridge_presence())
            await pilot.pause()
            await pilot.click("#bridge-presence-yes")
            await shown
            widget = app.query_one("#work-presence")
            text = str(widget.content)
            assert "peer" in text and "idle" in text
            assert calls and calls[0][-1] == "agents"
            assert "connect" not in " ".join(calls[0])

    with capsys.disabled():
        asyncio.run(scenario())


def test_presence_line_uses_readable_names_and_stays_on_one_width():
    from rich.cells import cell_len
    from isycode.bridge_presence import presence_line

    rows = [
        {"name": "chatgpt_sse_01a0fe9afe9c7242", "status": "alive"},
        {"name": "claude_code_01a0fe9afe9c7242", "status": "alive"},
        {"name": "codex_visual_cat", "status": "alive"},
        {"name": "copilot_20261004_033922", "status": "alive"},
        {"name": "peer", "status": "idle"},
    ]
    wide = presence_line(rows, 160)
    assert "ChatGPT" in wide and "Claude" in wide and "peer" in wide and "idle" in wide
    assert "01a0fe" not in wide and "20261004" not in wide and "chatgpt_sse" not in wide
    assert cell_len(wide) <= 160
    narrow = presence_line(rows, 40)
    assert cell_len(narrow) <= 40
    assert "01a0fe" not in narrow and "20261004" not in narrow
    single = presence_line([{"name": "peer", "status": "idle"}])
    assert single == "peer idle"


def test_real_button_message_pump_can_cancel_modal(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    async def run():
        app=TUIApp()
        async with app.run_test(size=(140,40)) as pilot:
            await pilot.pause()
            await app._show_chat_sessions()
            await pilot.pause()
            await asyncio.wait_for(pilot.click('#work-bridge'), 3)
            await pilot.pause()
            assert app.screen.id=='bridge-presence'
            await asyncio.wait_for(pilot.press('escape'), 3)
            await pilot.pause()
            assert app.screen.id!='bridge-presence'
            await pilot.click('#work-hide')
            await pilot.pause()
            assert not app.query_one('#work-list').display
    asyncio.run(run())
