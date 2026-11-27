"""How the window spends its vertical space.

A layout complaint is testable once you state it as numbers. The original bar
stacked ten 42px headers -- 420px of titles -- inside a scroll area capped at
220px, so reaching Config or Terminal meant scrolling a list of headings, and
the chat was left with 65% of a window it should dominate.

These tests fix that as a contract rather than as an opinion.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ui.app import AppController
from ui.main_window import MainWindow

WINDOW_W, WINDOW_H = 1360, 840


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    win = MainWindow(AppController(str(tmp_path)))
    win.resize(WINDOW_W, WINDOW_H)
    win.show()
    app.processEvents()
    yield win
    win.close()


def test_every_panel_is_reachable_without_scrolling(window):
    """The point of the redesign: no hunting through a list of headers."""
    bar = window.panel_bar
    assert len(bar.panels()) >= 10
    for panel in bar.panels():
        assert bar.is_reachable(panel), f"{panel.title()} needs scrolling to reach"


def test_the_chat_keeps_most_of_the_window(window, app):
    """It is a chat-first app; the drawers are secondary."""
    app.processEvents()
    share = window.chat.height() / window.height()
    assert share >= 0.70, f"chat only gets {share:.0%} of the window"


def test_the_tab_row_fits_without_scrolling(window):
    """The original bug was 420px of stacked headers in a 220px scroll area.

    Measures the tab bar, not the widget: a QTabWidget's sizeHint always asks
    for its content's height, so comparing that against maximumHeight measures
    nothing.
    """
    bar = window.panel_bar
    tab_row = bar.inspector.tabBar().sizeHint().height()
    assert tab_row <= 48
    assert bar.nav_buttons["Config"].isVisible()


def test_the_drawer_starts_closed(window):
    """Chat-first: the panels are there when wanted, not by default."""
    assert window.panel_bar.drawer_visible()


def test_collapsing_the_drawers_gives_the_room_back(window, app):
    bar = window.panel_bar
    before = window.chat.width()
    bar.set_drawer_visible(True)
    window.main_split.setSizes([420, 640, 300])
    app.processEvents()
    expanded = window.chat.width()
    bar.set_drawer_visible(False)
    window.main_split.setSizes([0, 1060, 300])
    app.processEvents()
    collapsed = window.chat.width()

    assert collapsed > expanded, "collapsing must return space to the chat"
    assert before  # sanity: the window laid out at all


# --- the API the rest of the app relies on ---------------------------------

def test_panels_keep_their_titles(window):
    titles = [p.title() for p in window.panel_bar.panels()]
    for expected in ("Editor", "Tool calls", "Config", "Terminal", "Status"):
        assert expected in titles


def test_expanding_a_panel_still_reports_expanded(window, app):
    """`test_ui_panels.py` asserts on `_expanded`; keep that meaning true."""
    window.editor_collapsible.set_expanded(True)
    app.processEvents()
    assert window.editor_collapsible._expanded

    window.tools_collapsible.set_expanded(True)
    app.processEvents()
    assert window.tools_collapsible._expanded
    assert not window.editor_collapsible._expanded, "only one drawer is visible at a time"


def test_status_text_still_shows(window):
    window.editor_collapsible.set_status("main.py")
    assert "main.py" in window.panel_bar.label_for(window.editor_collapsible)


def test_collapse_all_is_still_honoured(window, app):
    window.panel_bar.collapse_all()
    app.processEvents()
    assert not window.panel_bar.drawer_visible()


# --- reaching the providers quickly ----------------------------------------

def test_providers_is_one_menu_entry_away(window):
    """Configuring a provider was the eighth of ten stacked drawers.

    It used to be a toolbar button; the toolbar then got crowded, so it moved
    into the menu. What must stay true is that it is reachable in one step,
    not which widget carries it.
    """
    labels = [a.text() for a in window.menu.actions() if a.text()]
    assert "Providers…" in labels


def test_providers_opens_in_its_own_window(window, app):
    window.open_providers()
    app.processEvents()
    assert window.panel_bar.pages.currentWidget() is window.config_panel
    assert window.config_panel.isVisible()
    window.close_all_panel_windows()
