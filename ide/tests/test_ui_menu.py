"""One menu button instead of a crowded toolbar, and panels in their own windows.

The toolbar carried two combos and four buttons competing for the same row.
Now it keeps only what is touched constantly -- provider and model -- and
everything else lives behind a single menu. Choosing an entry opens that panel
in its own window: separate, movable, still driven by the same controller.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from ui.app import AppController
from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    win = MainWindow(AppController(str(tmp_path)))
    win.resize(1360, 840)
    win.show()
    app.processEvents()
    yield win
    win.close_all_panel_windows()
    win.close()


# --- the toolbar stops competing for space ---------------------------------

def test_the_toolbar_keeps_only_what_is_used_constantly(window):
    """Provider and model change often; everything else does not."""
    texts = [w.text() for w in window.toolbar_buttons()]
    assert window.menu_button.text() in texts
    assert "PLAN" in texts and "CODER" in texts
    assert window.panel_bar.conversation_button.text() == "Conversación"
    assert window.panel_bar.code_button.text() == "Código + chat"


def test_the_menu_holds_the_actions_that_left_the_toolbar(window):
    labels = [a.text() for a in window.menu.actions() if a.text()]
    for expected in ("Providers…", "Open workspace…", "Clear chat"):
        assert expected in labels, f"{expected} missing from the menu; have {labels}"


def test_every_panel_is_offered_in_the_menu(window):
    labels = window.panel_menu_labels()
    for expected in ("Editor", "Tool calls", "Config", "Terminal", "Status"):
        assert expected in labels


# --- panels open as separate windows ---------------------------------------

def test_opening_a_panel_creates_its_own_window(window, app):
    dialog = window.open_panel_window("Config")
    app.processEvents()
    assert isinstance(dialog, QDialog)
    assert dialog.isVisible()
    assert dialog.windowTitle()


def test_the_panel_window_is_not_modal(window, app):
    """It has to stay usable alongside the chat, not block it."""
    dialog = window.open_panel_window("Terminal")
    app.processEvents()
    assert not dialog.isModal()


def test_asking_twice_reuses_the_same_window(window, app):
    first = window.open_panel_window("Editor")
    app.processEvents()
    second = window.open_panel_window("Editor")
    app.processEvents()
    assert first is second, "a second click must raise the window, not clone it"


def test_the_panel_widget_moves_into_the_window_not_a_copy(window, app):
    """The window shows the live panel, so it keeps working."""
    dialog = window.open_panel_window("Config")
    app.processEvents()
    assert window.config_panel.window() is dialog


def test_closing_a_panel_window_returns_the_panel(window, app):
    """Closing must not strand the widget in a destroyed parent."""
    dialog = window.open_panel_window("Config")
    app.processEvents()
    dialog.close()
    app.processEvents()
    assert window.config_panel is not None
    again = window.open_panel_window("Config")
    app.processEvents()
    assert again.isVisible()


def test_providers_opens_the_config_window(window, app):
    window.open_providers()
    app.processEvents()
    assert window.config_panel.window().isVisible()


def test_close_all_shuts_every_panel_window(window, app):
    window.open_panel_window("Config")
    window.open_panel_window("Terminal")
    app.processEvents()
    window.close_all_panel_windows()
    app.processEvents()
    assert not window.panel_windows
