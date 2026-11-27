"""Local installation check using an owned disposable project, no account calls."""
import asyncio
import json
import os
import tempfile
from pathlib import Path


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="isycode-ide-check-") as directory:
        os.environ["ISYCODE_IDE_HOME"] = str(Path(directory) / "state")
        from PySide6.QtWidgets import QApplication
        from core.runtime.linux import LinuxCommandRuntime
        from ui.app import AppController
        from ui.main_window import MainWindow
        from ui.theme import apply_theme
        app = QApplication.instance() or QApplication([])
        apply_theme(app)
        project = Path(directory) / "project"
        project.mkdir()
        window = MainWindow(AppController(project))
        window.resize(1024, 768)
        window.show()
        app.processEvents()
        runtime = LinuxCommandRuntime(project)
        request = runtime.prepare({"argv": ["/usr/bin/true"]})
        asyncio.run(runtime.check_capabilities(request))
        report = {"name": "ISyCode IDE", "qt": True, "linux_namespaces": True,
                  "views": ["conversation", "code"], "account_requests": 0}
        window.close()
        app.processEvents()
        print(json.dumps(report))
        return 0
