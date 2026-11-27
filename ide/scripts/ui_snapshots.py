"""Render every IDE page offscreen and save PNGs (UI/UX visual regression aid).

Usage: QT_QPA_PLATFORM=offscreen .venv/bin/python -P scripts/ui_snapshots.py OUT_DIR [WORKSPACE]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.app import AppController  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.shell import NAVIGATION  # noqa: E402
from ui.theme import apply_theme  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ws = Path(sys.argv[2] if len(sys.argv) > 2 else Path.cwd()).resolve()
    app = QApplication(sys.argv[:1])
    apply_theme(app)
    win = MainWindow(controller=AppController(ws))
    win.resize(1920, 1040)
    win.show()

    def pump(ms: int = 400) -> None:
        end = QTimer()
        end.setSingleShot(True)
        end.start(ms)
        while end.isActive():
            app.processEvents()

    pump(1200)
    shell = win.panel_bar
    for i, (title, label, _sym) in enumerate(NAVIGATION):
        if title == "GitHub":
            continue  # avoids network/gh calls during snapshots
        shell.show_title(title)
        pump(500)
        win.grab().save(str(out / f"{i:02d}_{label.replace(' ', '_')}.png"))
    print(f"saved to {out}")
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
