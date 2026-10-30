import os
from unittest.mock import patch

from isycode.tui_theme import (
    _authority_capability_label,
    _semantic_box_title,
    ascii_only,
    banner_text,
    set_ascii_only,
    status_chip,
    status_phrase,
    switch_row,
    switch_rows,
)


def test_ascii_only_toggle():
    original = ascii_only()
    try:
        set_ascii_only(True)
        assert ascii_only() is True

        set_ascii_only(False)
        assert ascii_only() is False
    finally:
        set_ascii_only(original)


def test_no_color_env_initialization():
    with patch.dict(os.environ, {"NO_COLOR": "1"}):
        import importlib
        import isycode.tui_theme as theme_mod
        importlib.reload(theme_mod)
        assert theme_mod.ascii_only() is True

    with patch.dict(os.environ, {}, clear=True):
        import isycode.tui_theme as theme_mod
        importlib.reload(theme_mod)
        assert theme_mod.ascii_only() is False


def test_authority_capability_label():
    try:
        set_ascii_only(False)
        label_on = _authority_capability_label("Filesystem write", True)
        assert "✓ on" in label_on.plain

        label_off = _authority_capability_label("Filesystem write", False)
        assert "− off" in label_off.plain

        set_ascii_only(True)
        label_ascii_on = _authority_capability_label("Filesystem write", True)
        assert "[ON]" in label_ascii_on.plain

        label_ascii_off = _authority_capability_label("Filesystem write", False)
        assert "[OFF]" in label_ascii_off.plain
    finally:
        set_ascii_only(False)


def test_banner_text():
    try:
        set_ascii_only(False)
        unicode_banner = banner_text()
        assert "ISYCODE" in unicode_banner.plain or "█" in unicode_banner.plain

        set_ascii_only(True)
        ascii_banner = banner_text()
        assert "ISYCODE" in ascii_banner.plain
        assert "█" not in ascii_banner.plain
    finally:
        set_ascii_only(False)


def test_status_phrase():
    assert status_phrase("ready for input") == "Ready For Input"
    assert status_phrase("PATH /home/user MCPs 1/2") == "PATH /home/user MCPs 1/2"
    assert status_phrase("ok") == "Ok"


def test_status_chip():
    chip = status_chip("ready")
    assert "Ready" in chip


def test_switch_row_and_rows():
    try:
        set_ascii_only(False)
        row_on = switch_row(True, "Network")
        assert "✓ " in row_on.plain and "Network" in row_on.plain

        row_off = switch_row(False, "Filesystem")
        assert "✗ " in row_off.plain and "Filesystem" in row_off.plain

        row_none = switch_row(None, "MCP")
        assert "··· " in row_none.plain

        row_inactive = switch_row(True, "LSP", inactive=True)
        assert "○ " in row_inactive.plain

        set_ascii_only(True)
        row_ascii_on = switch_row(True, "Network")
        assert "[x] " in row_ascii_on.plain

        row_ascii_off = switch_row(False, "Filesystem")
        assert "[ ] " in row_ascii_off.plain

        row_ascii_none = switch_row(None, "MCP")
        assert "... " in row_ascii_none.plain

        row_ascii_inactive = switch_row(True, "LSP", inactive=True)
        assert "[-] " in row_ascii_inactive.plain

        combined = switch_rows([row_ascii_on, row_ascii_off])
        assert "[x] Network\n[ ] Filesystem" in combined.plain
    finally:
        set_ascii_only(False)


def test_semantic_box_title():
    t_completed = _semantic_box_title("workspace_run · completed")
    assert "workspace_run" in t_completed.plain
    assert "completed" in t_completed.plain

    t_denied = _semantic_box_title("fs.read · denied")
    assert "denied" in t_denied.plain

    t_failed = _semantic_box_title("bash · failed")
    assert "failed" in t_failed.plain
