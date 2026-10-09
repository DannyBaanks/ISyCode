"""The user can inspect, opt in, opt out and recover original output."""
import asyncio
import importlib.util
from pathlib import Path

import pytest
from textual.widgets import Button, Static


def test_rtk_settings_surface_exists():
    assert importlib.util.find_spec('isycode.rtk_tui'), 'RTK settings screen is missing'


def test_settings_menu_and_slash_route_are_wired():
    from isycode.tui import TUIApp
    from isycode.tui_app_menu import MENU_DISPATCH
    assert 'rtk_settings' in MENU_DISPATCH
    assert hasattr(TUIApp, '_menu_rtk_settings')


@pytest.mark.asyncio
async def test_settings_enable_pins_displayed_binary_then_disable(tmp_path, monkeypatch):
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    from isycode.rtk_tui import RTKSettingsScreen
    from isycode.rtk_integration import Settings
    configure(tmp_path, monkeypatch)
    identity = {'enabled': True, 'path': '/usr/local/bin/rtk', 'sha256': 'a' * 64,
                'version': 'rtk 0.51.0'}
    monkeypatch.setattr(Settings, 'inspect', lambda self: identity)
    app = TUIApp()
    async with app.run_test(size=(120, 42)) as pilot:
        app.push_screen(RTKSettingsScreen())
        await pilot.pause(0.1)
        screen = app.screen
        assert str(screen.query_one('#rtk-identity', Static).render()).find('0.51.0') >= 0
        assert Settings().load()['enabled'] is False
        await pilot.click('#rtk-enable')
        await pilot.pause(0.1)
        assert Settings().load()['sha256'] == identity['sha256']
        await pilot.click('#rtk-disable')
        await pilot.pause(0.1)
        assert Settings().load() == {'enabled': False}


def test_rtk_ask_does_not_inherit_quiet_classic(tmp_path):
    from isycode.tui import TUIApp
    from isycode.security import ActionRequest
    app = TUIApp.__new__(TUIApp)
    request = ActionRequest('workspace.command.run', tmp_path, '/usr/bin/grep',
                            {'rtk': {'decision': 'ask'}})
    assert app._request_is_quiet(request) is False


def test_usage_label_does_not_claim_provider_token_savings(tmp_path):
    from isycode.rtk_integration import record_stats, savings_label
    record_stats(tmp_path, {'rtk': {'captured_bytes': 4000, 'saved_bytes': 2000}})
    assert savings_label(tmp_path) == 'RTK ~500 tok saved (50%)'
