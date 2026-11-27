"""ISyCode desktop entry point.

Usage:
    python -m ui.main [workspace_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ui.app import AppController
from ui.main_window import MainWindow
from ui.theme import apply_theme


def resolve_initial_workspace(explicit: str | Path | None = None) -> Path:
    """Prefer explicit path, then last saved project, then first linked repo, never defaulting to $HOME."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    home = Path.home().resolve()
    blocked = {home, Path("/")}
    try:
        from core.ui_preferences import UiPreferences
        last = UiPreferences().load().get("last_workspace", "").strip()
        if last:
            candidate = Path(last).expanduser().resolve()
            if candidate.is_dir() and candidate not in blocked:
                return candidate
    except Exception:
        pass
    try:
        from core.github_service import RepoLinkStore
        for link in RepoLinkStore().list():
            folder = str(link.get("folder", "")).strip()
            if folder:
                candidate = Path(folder).expanduser().resolve()
                if candidate.is_dir() and candidate not in blocked:
                    return candidate
    except Exception:
        pass
    cwd = Path.cwd().resolve()
    return cwd


def main(workspace: str | Path | None = None) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ISyCode IDE")
    app.setDesktopFileName("isycode-ide")
    app.setOrganizationName("ISyCo")
    
    icon_path = Path(__file__).parent / "assets" / "isycode.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    apply_theme(app)

    explicit = workspace or (sys.argv[1] if len(sys.argv) > 1 else None)
    working_dir = resolve_initial_workspace(explicit)
    window = MainWindow(controller=AppController(working_dir))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
