import importlib.util
from pathlib import Path

import pytest


def test_additive_installer_does_not_replace_existing_launchers(tmp_path, monkeypatch):
    file = Path(__file__).resolve().parents[1] / "packaging/install_ide.py"
    spec = importlib.util.spec_from_file_location("ide_install_fixture", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    image = tmp_path / "image with spaces.AppImage"
    image.write_text("#!/bin/sh\nexit 0\n")
    image.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setattr(module.sys if hasattr(module, "sys") else __import__('sys'), "argv", [str(file), str(image)])
    assert module.main() == 0
    command = home / ".local/bin/isycode-ide"
    desktop = home / ".local/share/applications/isycode-ide.desktop"
    assert "APPIMAGE_EXTRACT_AND_RUN=1" in command.read_text()
    assert "Name=ISyCode IDE" in desktop.read_text()
    assert "StartupWMClass=ISyCode IDE" in desktop.read_text()
    icon = home / ".local/share/icons/hicolor/256x256/apps/isycode-ide.png"
    assert "Icon=" + str(icon) + "\n" in desktop.read_text()
    assert icon.read_bytes() == (file.parent.parent / "ui/assets/isycode_256x256.png").read_bytes()
    before = {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}
    with pytest.raises(SystemExit):
        module.main()
    assert {path: path.read_bytes() for path in before} == before
