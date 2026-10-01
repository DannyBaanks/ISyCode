"""Workspace onboarding and named chat conversations remain scoped and private."""
from __future__ import annotations

from pathlib import Path

import pytest

from isycode.config import discover_workspace_identity
from isycode.workspace_setup import (
    WorkspaceSetupStore, broad_workspace_reason, new_workspace_choice, shared_root_warning,
)
from isycode.chat_sessions import ChatSessionStore


def test_accepting_recurrent_workspace_creates_empty_marker_and_remembers_choice(tmp_path: Path):
    launch = tmp_path / "Project"
    launch.mkdir()
    preferences = WorkspaceSetupStore(tmp_path / "state")

    assert preferences.recurrent_choice(launch) is None
    preferences.choose_recurrent(launch, True)

    marker = launch / ".isyroot"
    assert marker.is_file()
    assert marker.stat().st_size == 0
    assert preferences.recurrent_choice(launch) is True


def test_declining_recurrent_workspace_never_writes_into_launch_directory(tmp_path: Path):
    launch = tmp_path / "Temporary"
    launch.mkdir()
    preferences = WorkspaceSetupStore(tmp_path / "state")

    preferences.choose_recurrent(launch, False)

    assert preferences.recurrent_choice(launch) is False
    assert not (launch / ".isyroot").exists()
    assert list(launch.iterdir()) == []


def test_existing_marker_is_not_overwritten_by_setup(tmp_path: Path):
    launch = tmp_path / "AlreadyMarked"
    launch.mkdir()
    marker = launch / ".isyroot"
    marker.touch()
    preferences = WorkspaceSetupStore(tmp_path / "state")

    preferences.choose_recurrent(launch, True)

    assert marker.read_bytes() == b""


def test_chat_session_autonames_and_restores_message_history(tmp_path: Path):
    store = ChatSessionStore(tmp_path / "sessions")
    created = store.create("Fix the provider parser for nested config files")
    store.append(created.session_id, "user", "Fix the provider parser for nested config files")
    store.append(created.session_id, "assistant", "I will inspect the parser first.")

    restored = store.load(created.session_id)

    assert restored.title == "Fix the provider parser for nested config files"
    assert restored.messages == [
        {"role": "user", "content": "Fix the provider parser for nested config files"},
        {"role": "assistant", "content": "I will inspect the parser first."},
    ]
    assert store.list_sessions()[0].session_id == created.session_id


def test_session_names_are_bounded_and_workspace_stores_are_distinct(tmp_path: Path):
    root_a = tmp_path / "state" / "isyrcodesessions" / "workspace-a"
    root_b = tmp_path / "state" / "isyrcodesessions" / "workspace-b"
    a = ChatSessionStore(root_a)
    b = ChatSessionStore(root_b)
    session = a.create("A very long request " + "with lots of repeated details " * 12)

    assert len(session.title) <= 64
    assert b.list_sessions() == []


def test_session_store_rejects_symlink_root(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "sessions-link"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(ValueError, match="symlink"):
        ChatSessionStore(alias)


def test_session_can_be_renamed_and_found_by_transcript_search(tmp_path: Path):
    store = ChatSessionStore(tmp_path / "sessions")
    session = store.create("Debug the provider")
    store.append(session.session_id, "user", "Inspect nested provider config")
    renamed = store.rename(session.session_id, "Provider investigation")

    assert renamed.title == "Provider investigation"
    assert [item.session_id for item in store.search("nested config")] == [session.session_id]


def test_fork_preserves_only_messages_through_the_selected_index(tmp_path: Path):
    store = ChatSessionStore(tmp_path / "sessions")
    session = store.create("Original")
    store.append(session.session_id, "user", "first")
    store.append(session.session_id, "assistant", "second")
    store.append(session.session_id, "user", "third")

    child = store.fork(session.session_id, through_message=1)

    assert child.session_id != session.session_id
    assert child.messages == store.load(session.session_id).messages[:2]


def test_export_import_roundtrip_sanitizes_secrets_and_creates_new_identity(tmp_path: Path):
    store = ChatSessionStore(tmp_path / "sessions")
    session = store.create("Credential review")
    store.append(session.session_id, "user", "Use api_key=sk-secret-value only from the vault")

    exported = store.export_json(session.session_id)
    imported = store.import_json(exported)

    assert "sk-secret-value" not in exported
    assert "[redacted]" in exported
    assert imported.session_id != session.session_id
    assert imported.messages[0]["content"] == "Use api_key=[redacted] only from the vault"


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    (home / "projects" / "app").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    return home


def test_broad_directories_are_detected(fake_home: Path, tmp_path: Path):
    assert broad_workspace_reason(fake_home) is not None
    assert broad_workspace_reason(fake_home.parent) is not None
    assert broad_workspace_reason(Path(fake_home.anchor)) is not None
    assert broad_workspace_reason(tmp_path / "tmp") is not None
    assert broad_workspace_reason(fake_home / "projects" / "app") is None


def test_global_recurring_default_never_marks_a_broad_directory(fake_home: Path):
    assert new_workspace_choice(fake_home, None, "recurring") is None
    assert new_workspace_choice(fake_home.parent, None, "recurring") is None
    assert new_workspace_choice(fake_home / "projects" / "app", None, "recurring") is True


def test_saved_choice_and_other_defaults_keep_their_meaning(fake_home: Path):
    app = fake_home / "projects" / "app"
    assert new_workspace_choice(app, False, "recurring") is False
    assert new_workspace_choice(fake_home, True, "ask") is True
    assert new_workspace_choice(app, None, "temporary") is False
    assert new_workspace_choice(fake_home, None, "temporary") is False
    assert new_workspace_choice(app, None, "ask") is None


def test_recurring_default_keeps_projects_out_of_a_shared_home_root(fake_home: Path, tmp_path: Path):
    """Regression: launching from $HOME once must not make $HOME every project's root."""
    store = WorkspaceSetupStore(tmp_path / "state")
    app = fake_home / "projects" / "app"

    def startup(launch: Path):
        identity = discover_workspace_identity(launch)
        if identity.workspace_root_source != "isyroot":
            choice = new_workspace_choice(launch, store.recurrent_choice(launch), "recurring")
            if choice is not None:
                store.choose_recurrent(launch, choice)
            identity = discover_workspace_identity(launch)
        return identity

    home_identity = startup(fake_home)
    assert not (fake_home / ".isyroot").exists()
    assert home_identity.workspace_root_source == "fallback"

    project = startup(app)
    assert project.workspace_root == app.resolve()
    assert project.workspace_root_source == "isyroot"


def test_tui_startup_routes_the_global_default_through_the_broad_directory_guard():
    import ast

    source = (Path(__file__).resolve().parents[1] / "src" / "isycode" / "tui.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    startup = next(node for node in app.body
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == "_startup_workspace")
    segment = ast.get_source_segment(source, startup)
    assert "new_workspace_choice(" in segment
    assert '== "recurring"' not in segment


def test_existing_broad_marker_is_honoured_but_visibly_shared(fake_home: Path):
    """A pre-existing ~/.isyroot (older default or by hand) must not share silently."""
    (fake_home / ".isyroot").write_bytes(b"")
    app = fake_home / "projects" / "app"
    identity = discover_workspace_identity(app)
    assert identity.workspace_root == fake_home.resolve()
    warning = shared_root_warning(identity.workspace_root, identity.workspace_root_source, app)
    assert warning is not None and str(app) in warning and ".isyroot" in warning

    (app / ".isyroot").write_bytes(b"")
    own = discover_workspace_identity(app)
    assert shared_root_warning(own.workspace_root, own.workspace_root_source, app) is None


def test_fallback_roots_never_warn(fake_home: Path):
    assert shared_root_warning(fake_home, "fallback", fake_home) is None
