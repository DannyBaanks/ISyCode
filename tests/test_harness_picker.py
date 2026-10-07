import asyncio
import json
import stat
from pathlib import Path

import pytest

from isycode.file_picker import FilePickerUnavailable, choose_harness_folder
from isycode.harness_graph import CATALOG_IDS
from isycode.harness_store import HarnessStore


def test_harness_store_writes_versioned_known_root_map_private(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "picked"
    root.mkdir()
    store = HarnessStore()

    store.set_root("crush", root)

    assert store.roots() == {"crush": root.resolve()}
    assert json.loads(store.roots_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "roots": {"crush": str(root.resolve())},
    }
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.roots_path.stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        store.set_root("gemini", root)
    assert "gemini" not in CATALOG_IDS


def test_harness_store_rejects_group_readable_or_unknown_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    store = HarnessStore()
    root = tmp_path / "picked"
    root.mkdir()
    store.directory.mkdir(parents=True, exist_ok=True)
    store.roots_path.write_text(json.dumps({
        "version": 1,
        "roots": {"gemini": str(root)},
    }), encoding="utf-8")
    store.roots_path.chmod(0o600)
    with pytest.raises(ValueError):
        store.roots()

    store.roots_path.write_text(json.dumps({
        "version": 1,
        "roots": {"crush": str(root)},
    }), encoding="utf-8")
    store.roots_path.chmod(0o640)
    with pytest.raises(ValueError):
        store.roots()


def test_choose_harness_folder_reuses_native_directory_picker_with_harness_title(tmp_path, monkeypatch):
    initial = tmp_path / "home"
    initial.mkdir()
    picked = tmp_path / "picked"
    picked.mkdir()
    seen = {}

    monkeypatch.setattr("isycode.file_picker.sys.platform", "linux")
    monkeypatch.setattr("isycode.file_picker.shutil.which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)

    async def fake_run(argv, timeout):
        seen["argv"] = argv
        seen["timeout"] = timeout
        return picked

    monkeypatch.setattr("isycode.file_picker._run_picker", fake_run)
    result = asyncio.run(choose_harness_folder(
        initial, title="Choose the folder for Crush", timeout=12.0))
    assert result == picked
    assert "--directory" in seen["argv"]
    assert "--title=Choose the folder for Crush" in seen["argv"]
    assert seen["timeout"] == 12.0


def test_choose_harness_folder_rewords_picker_failure(tmp_path, monkeypatch):
    initial = tmp_path / "home"
    initial.mkdir()
    monkeypatch.setattr("isycode.file_picker.sys.platform", "linux")
    monkeypatch.setattr("isycode.file_picker.shutil.which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)

    async def fail(*args, **kwargs):
        raise FilePickerUnavailable("Context-file selection timed out.")

    monkeypatch.setattr("isycode.file_picker._run_picker", fail)
    with pytest.raises(FilePickerUnavailable, match="Folder selection for Crush failed"):
        asyncio.run(choose_harness_folder(initial, title="Choose the folder for Crush"))
