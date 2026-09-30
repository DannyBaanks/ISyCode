"""The default mode for new workspaces is a preference, never a grant."""
import ast
import json
from pathlib import Path

import pytest

from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority

SOURCE = Path(__file__).parent / "isycode" / "tui.py"


def test_default_mode_is_ask_and_round_trips(tmp_path):
    store = UserDefaultsStore(tmp_path)
    assert store.load()["new_workspace_mode"] == "ask"
    store.update(new_workspace_mode="classic")
    assert store.load()["new_workspace_mode"] == "classic"
    store.update(new_workspace="recurring")
    assert store.load()["new_workspace_mode"] == "classic"
    with pytest.raises(ValueError):
        store.update(new_workspace_mode="yolo")


def test_files_written_before_modes_still_load(tmp_path):
    store = UserDefaultsStore(tmp_path)
    store.path.write_text(json.dumps({"version": 1, "new_workspace": "ask", "default_role": None}))
    store.path.chmod(0o600)
    assert store.load()["new_workspace_mode"] == "ask"


def test_the_preference_alone_grants_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    UserDefaultsStore(tmp_path / "prefs").update(new_workspace_mode="classic")
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    assert authority.mode() is None
    assert authority.effective_policy()["grants"] == {}


def _method(name):
    source = SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    node = next(item for item in app.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
    return ast.get_source_segment(source, node)


def test_startup_uses_the_default_only_for_a_workspace_without_a_mode():
    startup = _method("_startup_workspace")
    assert startup.index("authority.mode() is None") < startup.index('get("new_workspace_mode", "ask")')
    assert startup.index('get("new_workspace_mode", "ask")') < startup.index("WorkspaceModeScreen(")


def test_choosing_classic_as_the_default_asks_first():
    setter = _method("_set_global_mode_default")
    assert setter.index("TailscaleConfirmScreen(") < setter.index("update(new_workspace_mode=value)")
