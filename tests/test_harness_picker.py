import asyncio
import json
import os
from pathlib import Path

import pytest

from isycode.file_picker import FilePickerUnavailable, choose_harness_folder
from isycode.harness_graph import CATALOG_IDS
from isycode.harness_store import HarnessStore
from isycode.platform_storage import storage


def _make_readable_by_other_users(path: Path) -> None:
    if os.name == "posix":
        path.chmod(0o640)
        return
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    owner = win32security.ConvertSidToStringSid(user)
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"O:{owner}D:P(A;;FA;;;{owner})(A;;FA;;;SY)(A;;GR;;;BU)",
        win32security.SDDL_REVISION_1)
    win32security.SetNamedSecurityInfo(
        str(path), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, descriptor.GetSecurityDescriptorDacl(), None)


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
    assert storage.private(store.directory)
    assert storage.private(store.roots_path)
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
    storage.protect(store.roots_path)
    with pytest.raises(ValueError):
        store.roots()

    store.roots_path.write_text(json.dumps({
        "version": 1,
        "roots": {"crush": str(root)},
    }), encoding="utf-8")
    _make_readable_by_other_users(store.roots_path)
    with pytest.raises(ValueError):
        store.roots()


def test_choose_harness_folder_reuses_native_directory_picker_with_harness_title(tmp_path, monkeypatch):
    initial = tmp_path / "home"
    initial.mkdir()
    picked = tmp_path / "picked"
    picked.mkdir()
    seen = {}

    monkeypatch.setattr("isycode.file_picker.os.name", "posix")
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
    monkeypatch.setattr("isycode.file_picker.os.name", "posix")
    monkeypatch.setattr("isycode.file_picker.sys.platform", "linux")
    monkeypatch.setattr("isycode.file_picker.shutil.which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)

    async def fail(*args, **kwargs):
        raise FilePickerUnavailable("Context-file selection timed out.")

    monkeypatch.setattr("isycode.file_picker._run_picker", fail)
    with pytest.raises(FilePickerUnavailable, match="Folder selection for Crush failed"):
        asyncio.run(choose_harness_folder(initial, title="Choose the folder for Crush"))
