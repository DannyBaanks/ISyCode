"""M-UX5: ASCII-only display fallback for terminals without Unicode.

State glyphs (✓/✗/○/···) and the banner art get plain-ASCII equivalents;
the switch is a user preference, never a grant.
"""
import pytest

from isycode.user_defaults import UserDefaultsStore


def test_ascii_only_defaults_off_and_round_trips(tmp_path):
    store = UserDefaultsStore(tmp_path)
    assert store.load()["ascii_only"] is False
    store.update(ascii_only=True)
    assert store.load()["ascii_only"] is True
    with pytest.raises(ValueError):
        store.update(ascii_only="yes")


def test_switch_row_uses_ascii_marks_when_enabled():
    from isycode.tui_theme import set_ascii_only, switch_row
    try:
        set_ascii_only(True)
        assert switch_row(True, "Reads").plain.startswith("[x]")
        assert switch_row(False, "Edits").plain.startswith("[ ]")
        assert switch_row(True, "Muted", inactive=True).plain.startswith("[-]")
        assert switch_row(None, "Pending").plain.startswith("...")
        set_ascii_only(False)
        assert switch_row(True, "Reads").plain.startswith("✓")
        assert switch_row(False, "Edits").plain.startswith("✗")
        assert switch_row(True, "Muted", inactive=True).plain.startswith("○")
        assert switch_row(None, "Pending").plain.startswith("···")
    finally:
        set_ascii_only(False)


def test_banner_falls_back_to_plain_ascii():
    from isycode.tui_theme import banner_text, set_ascii_only
    try:
        set_ascii_only(True)
        plain = banner_text().plain
        assert plain.isascii()
        assert "ISYCODE" in plain
    finally:
        set_ascii_only(False)


def test_capability_label_uses_bracketed_state():
    from isycode.tui_theme import _authority_capability_label, set_ascii_only
    try:
        set_ascii_only(True)
        assert "[ON]" in _authority_capability_label("Read", True).plain
        assert "[OFF]" in _authority_capability_label("Read", False).plain
    finally:
        set_ascii_only(False)


@pytest.mark.asyncio
async def test_settings_toggle_applies_immediately(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.tui import TUIApp
    from isycode.tui_theme import ascii_only
    app = TUIApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app._ascii_only is False
        app._menu_ascii_toggle({})
        assert app._ascii_only is True
        assert ascii_only() is True
        app._menu_ascii_toggle({})
        assert app._ascii_only is False
        assert ascii_only() is False
