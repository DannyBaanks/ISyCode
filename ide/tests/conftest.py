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
