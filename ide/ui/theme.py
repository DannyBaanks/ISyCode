"""Central theme for the ISyCode desktop GUI.

One palette, one global stylesheet. Widgets opt into roles through
objectName / dynamic properties instead of carrying inline colors, so the
whole app stays consistent and the look can change in one place.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QTableView

_THEME_ASSETS = (Path(__file__).parent / "assets" / "theme").as_posix()

# --- palette ---------------------------------------------------------------
BG = "#0c121a"          # window
SURFACE = "#101924"     # panels, chat background
SURFACE_2 = "#182433"   # cards, inputs
SURFACE_3 = "#23344a"   # hover
BORDER = "#2c435b"
BORDER_SOFT = "#203146"
TEXT = "#e8f1fa"
TEXT_DIM = "#adbed1"
TEXT_FAINT = "#859ab2"
ACCENT = "#08c7fa"      # ISyCode cyan
ACCENT_DIM = "#1f4a63"
OK = "#4ade80"
WARN = "#fbbf24"
ERR = "#f87171"
USER_BUBBLE = "#1d3a52"

MONO = "'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', Consolas, monospace"

# Diff colours used by ui/diff.py and the approval card.
DIFF_ADD_BG = "#16331f"
DIFF_ADD_FG = "#a6f0b8"
DIFF_DEL_BG = "#3a1b1e"
DIFF_DEL_FG = "#ffb4b4"
DIFF_HDR_FG = ACCENT
DIFF_CTX_FG = TEXT_DIM

# Syntax colours for the editor highlighter.
SYN_KEYWORD = "#c792ea"
SYN_STRING = "#c3e88d"
SYN_COMMENT = "#6b7385"


STYLESHEET = f"""
* {{
    color: {TEXT};
    font-size: 14px;
}}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#chatScrollBody, QScrollArea#chatScroll {{ background: {SURFACE}; border: none; }}

QToolTip {{
    background: {SURFACE_2}; color: {TEXT};
    border: 1px solid {BORDER}; padding: 4px 6px; border-radius: 4px;
}}

/* toolbar + status bar */
QToolBar {{
    background: {BG}; border: none; border-bottom: 1px solid {BORDER_SOFT};
    padding: 4px 8px; spacing: 6px;
}}
QToolBar QLabel {{ color: {TEXT_DIM}; }}
QToolBar#ideToolbar {{ padding: 8px 10px; spacing: 12px; }}
QLabel#ideBrand {{ color: {TEXT}; font-size: 18px; font-weight: 700; padding-right: 10px; }}
QFrame#ideNavigation {{ background: {BG}; border-right: 1px solid {BORDER_SOFT}; }}
QPushButton#ideNavigationItem {{
    text-align: left; padding: 11px 10px; background: transparent;
    color: {TEXT_DIM}; border: none; border-left: 3px solid transparent;
    border-radius: 6px; min-height: 22px;
}}
QPushButton#ideNavigationItem:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#ideNavigationItem:checked {{
    background: #0d3043; color: {TEXT}; border-left-color: {ACCENT};
}}
QWidget#ideWorkPage, QStackedWidget#idePages {{ background: {BG}; }}
QLabel#conversationTitle {{ font-size: 17px; font-weight: 600; }}
QWidget#modeSegment {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 15px; }}
QPushButton#viewSwitch, QPushButton#modeSwitch {{ background: transparent; border-radius: 12px; color: {TEXT_DIM}; min-height: 24px; padding: 6px 16px; }}
QPushButton#viewSwitch:checked, QPushButton#modeSwitch:checked {{ background: {ACCENT}; color: #05202b; font-weight: 700; border-color: {ACCENT}; }}
QTabWidget#ideInspector {{ border-left: 1px solid {BORDER_SOFT}; }}
QLabel#pageTitle {{ font-size: 27px; font-weight: 700; padding: 2px 0; }}
QLabel#pageSubtitle {{ color: {TEXT_DIM}; font-size: 14px; padding-bottom: 14px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 24px; padding: 6px 4px 4px 4px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 2px; top: 0px; padding: 0 4px 4px 4px; color: {TEXT}; font-weight: 700; font-size: 15px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {TEXT_DIM}; border-radius: 4px; background: {SURFACE_2}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({_THEME_ASSETS}/check.svg); }}
QCheckBox::indicator:disabled {{ border-color: {BORDER}; background: {SURFACE}; }}
QStatusBar {{ background: {BG}; border-top: 1px solid {BORDER_SOFT}; color: {TEXT_DIM}; }}
QStatusBar QLabel {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#modeBadge {{
    border-radius: 9px; padding: 1px 10px; font-size: 11px; font-weight: 600;
}}
QLabel#modeBadge[mode="plan"] {{ background: #3b2f12; color: {WARN}; }}
QLabel#modeBadge[mode="coder"] {{ background: {ACCENT_DIM}; color: {ACCENT}; }}
QLabel#contextMeter[level="ok"] {{ color: {OK}; }}
QLabel#contextMeter[level="warn"] {{ color: {WARN}; }}
QLabel#contextMeter[level="err"] {{ color: {ERR}; }}

QToolButton#menuButton {{
    border: none; padding: 4px 10px; font-size: 16px; border-radius: 6px;
}}
QToolButton#menuButton:hover {{ background: {SURFACE_3}; }}
QToolButton#menuButton::menu-indicator {{ image: none; }}

/* menus */
QMenu {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; padding: 4px; border-radius: 8px;
}}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

/* inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 8px; selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox {{
    padding-right: 26px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid {BORDER};
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background: {SURFACE_3};
}}
QComboBox::down-arrow {{
    image: url({_THEME_ASSETS}/chevron-down.svg);
    width: 12px; height: 12px;
}}
QComboBox::down-arrow:hover, QComboBox::down-arrow:on {{
    image: url({_THEME_ASSETS}/chevron-down-hover.svg);
}}
QSpinBox {{ max-width: 160px; padding-right: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 18px; background: {SURFACE_3}; border: none;
}}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QSpinBox::up-arrow {{ image: url({_THEME_ASSETS}/chevron-up.svg); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({_THEME_ASSETS}/chevron-down.svg); width: 10px; height: 10px; }}
QSpinBox:disabled, QLineEdit:disabled, QComboBox:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; border-color: {BORDER_SOFT}; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {SURFACE_3};
}}
QPlainTextEdit#monoView, QTextEdit#monoView {{
    font-family: {MONO}; font-size: 12px; background: {SURFACE};
}}

/* buttons */
QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; border-color: {BORDER_SOFT}; }}
QPushButton[variant="primary"] {{
    background: {ACCENT}; color: #06131c; border: none; font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: #7dd3ff; }}
QPushButton[variant="primary"]:disabled {{ background: {SURFACE}; color: {TEXT_FAINT}; border: 1px solid {BORDER_SOFT}; font-weight: 500; }}
QPushButton[variant="danger"] {{ color: {ERR}; border-color: #5a2a2e; background: transparent; }}
QPushButton[variant="danger"]:hover {{ background: {DIFF_DEL_BG}; }}
QPushButton[variant="danger"]:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER_SOFT}; }}
QPushButton[variant="approve"] {{ background: #1f7a3f; color: white; border: none; font-weight: 600; }}
QPushButton[variant="approve"]:hover {{ background: #26924b; }}
QPushButton[variant="ghost"] {{
    background: transparent; border: 1px solid transparent; color: {TEXT_DIM};
    padding: 3px 10px; font-size: 12px;
}}
QPushButton[variant="ghost"]:hover {{ background: {SURFACE_3}; color: {TEXT}; }}
QPushButton#scrollBottom {{
    background: {ACCENT}; color: #06131c; border: none; border-radius: 14px;
    font-size: 11px; font-weight: 600;
}}

/* chat */
QFrame#composer {{ background: {BG}; border-top: 1px solid {BORDER_SOFT}; }}
QPlainTextEdit#promptComposer {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 8px 12px; font-size: 13px;
}}
QPlainTextEdit#promptComposer:focus {{ border-color: {ACCENT}; }}
QLabel#composerStatus[state="ready"] {{ color: {OK}; }}
QLabel#composerStatus[state="working"] {{ color: {ACCENT}; }}
QLabel#composerStatus[state="error"] {{ color: {ERR}; }}
QLabel#composerStats, QLabel#composerHint {{ color: {TEXT_FAINT}; font-size: 12px; }}

QTextBrowser#userBubble {{
    background: {USER_BUBBLE}; border: 1px solid #27506f; border-radius: 12px; padding: 6px 10px;
}}
QFrame#assistantBubble {{
    background: transparent; border: none;
}}
QTextBrowser#assistantBody {{ background: transparent; border: none; padding: 0; }}
QLabel#bubbleAuthor {{ color: {TEXT}; font-weight: 600; font-size: 15px; }}
QLabel#bubbleAuthorUser {{ color: {TEXT_DIM}; font-weight: 600; font-size: 12px; }}
QLabel#systemMessage {{ color: {TEXT_FAINT}; font-size: 12px; padding: 2px 6px; }}

QFrame#toolCard {{
    background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-left: 3px solid {TEXT_FAINT};
    border-radius: 8px;
}}
QFrame#toolCard[state="ok"] {{ border-left-color: {OK}; }}
QFrame#toolCard[state="fail"] {{ border-left-color: {ERR}; }}
QFrame#toolCard[state="running"] {{ border-left-color: {ACCENT}; }}
QLabel#toolTitle {{ font-family: {MONO}; font-size: 12px; font-weight: 600; }}
QLabel#toolArgs {{ font-family: {MONO}; font-size: 12px; color: {TEXT_DIM}; }}
QLabel#toolStatus {{ font-size: 12px; color: {TEXT_DIM}; }}

QFrame#approvalCard {{
    background: {SURFACE}; border: 1px solid #176182; border-radius: 10px;
}}
QFrame#approvalCard[decision="approved"] {{ background: #13261a; border-color: #2f6b40; }}
QFrame#approvalCard[decision="rejected"] {{ background: #2a1517; border-color: #6b2f33; }}
QLabel#approvalTitle {{ color: {TEXT}; font-weight: 600; font-size: 15px; }}
QLabel#approvalBadge {{ color: {TEXT_DIM}; font-size: 11px; font-weight: 600; }}
QFrame#approvalCard[decision="approved"] QLabel#approvalBadge {{ color: {OK}; }}
QFrame#approvalCard[decision="rejected"] QLabel#approvalBadge {{ color: {ERR}; }}
QTextBrowser#approvalDiff {{ background: {SURFACE}; font-family: {MONO}; font-size: 12px; }}

/* empty state */
QWidget#emptyState QLabel#emptyTitle {{
    color: {TEXT}; font-size: 28px; font-weight: 700; letter-spacing: 6px;
}}
QWidget#emptyState QLabel#emptySubtitle {{ color: {TEXT_DIM}; font-size: 13px; }}
QWidget#emptyState QLabel#emptyKeys {{ color: {TEXT_FAINT}; font-size: 12px; }}

/* workspace + trees + tables */
QWidget#workspacePanel {{ background: {BG}; }}
QLabel#sectionTitle {{
    color: {TEXT_DIM}; font-size: 11px; font-weight: 700; letter-spacing: 1px;
}}
QLabel#gitLabel {{ color: {TEXT_FAINT}; font-size: 12px; }}
QTreeView, QListWidget, QTreeWidget, QTableWidget {{
    background: {BG}; border: none; outline: none; alternate-background-color: {SURFACE};
}}
QTreeView::item, QListWidget::item, QTreeWidget::item {{ padding: 3px 4px; border-radius: 4px; }}
QTreeView::item:hover, QListWidget::item:hover, QTreeWidget::item:hover {{ background: {SURFACE_2}; }}
QTreeView::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {ACCENT_DIM}; color: {TEXT};
}}
QHeaderView::section {{
    background: {SURFACE}; color: {TEXT_DIM}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 6px 10px; font-size: 12px; font-weight: 600;
}}
QTableWidget {{ gridline-color: {BORDER_SOFT}; }}

QFrame#githubMetric, QFrame#githubLocalCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#repoTitle {{ font-size: 26px; font-weight: 700; }}
QLabel#repoDescription {{ color: {TEXT_DIM}; font-size: 15px; }}
QLabel#repoMetadata {{ color: {TEXT_FAINT}; font-size: 12px; }}
QLabel#metricCaption {{ color: {TEXT_FAINT}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel#metricValue {{ color: {ACCENT}; font-size: 18px; font-weight: 600; }}
QLabel#githubSectionTitle {{ font-size: 18px; font-weight: 600; }}
QLabel#githubAccount {{ color: {TEXT_DIM}; font-size: 14px; }}
QLabel#githubAccount[verified="true"] {{ color: {OK}; }}
QLabel#syncCount {{ color: {WARN}; font-size: 19px; font-weight: 600; }}
QTreeWidget#githubRepositories::item {{ padding: 10px; border-bottom: 1px solid {BORDER_SOFT}; border-radius: 8px; }}
QTextBrowser#githubActivity {{ background: {SURFACE}; border: none; padding: 14px; }}

/* drawer tabs */
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER_SOFT}; background: {SURFACE}; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_DIM}; padding: 9px 16px; margin-right: 2px;
    border: none; border-bottom: 2px solid transparent; font-size: 13px; font-weight: 500;
}}
QTabBar::tab:hover {{ color: {TEXT}; background: {SURFACE_2}; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom-color: {ACCENT}; font-weight: 600; background: {SURFACE}; }}
QTabBar QToolButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER_SOFT}; border-radius: 3px;
    color: {TEXT_DIM};
}}
QTabBar QToolButton:hover {{ background: {SURFACE_3}; color: {TEXT}; }}
QPushButton#drawerToggle {{
    border: none; background: transparent; color: {TEXT_DIM}; padding: 0; border-radius: 4px;
}}
QPushButton#drawerToggle:hover {{ background: {SURFACE_3}; color: {TEXT}; }}

QLabel#hostShellBanner {{
    background: #2a2412; color: {WARN}; border: 1px solid #6b5517;
    border-radius: 6px; padding: 8px 10px; font-size: 13px;
}}

/* splitters + scrollbars */
QSplitter::handle {{ background: {BORDER_SOFT}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* command palette */
QDialog#commandPalette {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QDialog#commandPalette QLineEdit {{ font-size: 14px; padding: 8px 10px; }}
QListWidget#conversationList::item {{ padding: 6px 8px; border-radius: 6px; color: {TEXT_DIM}; }}
QListWidget#conversationList::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; border-left: 3px solid {ACCENT}; }}
QDialog#commandPalette QListWidget {{ background: {SURFACE_2}; }}

/* ChatGPT-style sidebar & vertical navigation */
QWidget#chatgptSidebar {{
    background: {BG};
    border-right: 1px solid {BORDER_SOFT};
}}
QLabel#sectionTitle {{
    font-size: 12px;
    font-weight: 700;
    color: {TEXT_FAINT};
    letter-spacing: 1.2px;
}}
QListWidget#chatgptNavList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 2px;
}}
QListWidget#chatgptNavList::item {{
    color: {TEXT_DIM};
    border-radius: 6px;
    padding: 7px 10px;
    margin-bottom: 2px;
    font-size: 13px;
    font-weight: 500;
}}
QListWidget#chatgptNavList::item:hover {{
    color: {TEXT};
    background: {SURFACE_2};
}}
QListWidget#chatgptNavList::item:selected {{
    color: {TEXT};
    background: {SURFACE_3};
    font-weight: 600;
}}

/* Panel help / info button */
QPushButton#helpButton {{
    background: {SURFACE_2};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-radius: 11px;
    font-size: 11px;
    font-weight: bold;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    padding: 0;
}}
QPushButton#helpButton:hover {{
    background: {ACCENT_DIM};
    color: {ACCENT};
    border-color: {ACCENT};
}}

/* Status panel cards */
QFrame#statusCard {{
    background: {SURFACE_2};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    padding: 10px;
}}
QLabel#statusCardTitle {{
    font-size: 12px;
    font-weight: 700;
    color: {TEXT_FAINT};
    letter-spacing: 1px;
}}
QLabel#statusCardValue {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT};
}}
"""

# Inline CSS for rich-text documents (QTextBrowser does not read QSS).
DOCUMENT_CSS = f"""
body {{ color: {TEXT}; font-size: 15px; }}
a {{ color: {ACCENT}; }}
p {{ margin: 0 0 6px 0; }}
pre {{
    background: {BG}; color: {TEXT}; padding: 10px; border: 1px solid {BORDER_SOFT};
    font-family: {MONO}; font-size: 12px; white-space: pre-wrap;
}}
code {{ font-family: {MONO}; font-size: 12px; background: {BG}; color: #ffd580; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid {BORDER}; padding: 4px 8px; }}
th {{ background: {SURFACE}; }}
blockquote {{ color: {TEXT_DIM}; border-left: 3px solid {BORDER}; padding-left: 8px; }}
"""


def repolish(widget) -> None:
    """Re-apply the stylesheet after changing a dynamic property."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class _TablePolisher(QObject):
    """Hide Qt's numeric row header on every table; rows already carry their own identity."""

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.Polish and isinstance(obj, QTableView) and not obj.property("keepRowNumbers"):
            obj.verticalHeader().setVisible(False)
        return False


_POLISHER: _TablePolisher | None = None


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE_2))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE_2))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT_DIM))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_2))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_FAINT))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    app.setPalette(palette)
    font = QFont("Lato")
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
    global _POLISHER
    if _POLISHER is None:
        _POLISHER = _TablePolisher(app)
        app.installEventFilter(_POLISHER)
