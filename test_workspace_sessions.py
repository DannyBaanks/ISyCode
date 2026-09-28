"""Workspace onboarding and named chat conversations remain scoped and private."""
from __future__ import annotations

from pathlib import Path

import pytest

from isycode.workspace_setup import WorkspaceSetupStore
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
