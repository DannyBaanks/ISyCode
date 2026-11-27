"""Configuracion de pytest para IsyVM tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Hacer importable el paquete bridge desde tests
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pytest


@pytest.fixture(autouse=True)
def private_ide_state(tmp_path, monkeypatch):
    """No test may read or modify the user's IDE state or OS keyring."""
    monkeypatch.setenv("ISYCODE_IDE_HOME", str(tmp_path / "ide-state"))
    import keyring
    values = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: values.get((service, name)))
    monkeypatch.setattr(keyring, "set_password", lambda service, name, value: values.__setitem__((service, name), value))
    def remove(service, name):
        if (service, name) not in values:
            raise keyring.errors.PasswordDeleteError("absent fixture credential")
        values.pop((service, name))
    monkeypatch.setattr(keyring, "delete_password", remove)


def pytest_sessionfinish(session, exitstatus):
    """Tear Qt down while the QApplication is still alive.

    Tests leave top-level widgets behind. At interpreter exit
    PySide::destroyQCoreApplication walks every wrapper still registered and
    deletes it; one already freed by its C++ parent crashes the run (exit 139)
    after every test passed. Stop detached workers, close and delete the
    leftovers, and flush the deferred deletes before Python finalizes.
    """
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    try:
        from ui.panels.config import drain_inspections
        drain_inspections()
    except ImportError:
        pass
    for widget in list(QApplication.topLevelWidgets()):
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:  # already destroyed on the C++ side
            continue
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    import gc
    gc.collect()
