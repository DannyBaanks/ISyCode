"""A hard link inside the workspace may name a file that lives outside it."""
import json
import os

import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.workspace_authority import WorkspaceAuthority

CANARY = "outside-canary-not-for-chat"


@pytest.fixture
def linked(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text(CANARY + "\n", encoding="utf-8")
    try:
        os.link(outside, root / "linked.txt")
    except OSError:
        pytest.skip("NOT_DEMONSTRATED: this filesystem does not allow hard links")
    (root / "plain.txt").write_text(CANARY.upper() + " plain\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[root])
    return LocalWorkspaceReadOwner(root, authority)


def test_read_refuses_a_file_with_another_hard_link(linked):
    outcome = linked.execute("workspace.files.read", {"path": "linked.txt"})

    assert outcome.decision == "ERROR"
    assert "hard link" in outcome.reason
    assert CANARY not in outcome.text


def test_grep_skips_hard_linked_files_but_keeps_ordinary_ones(linked):
    outcome = linked.execute("workspace.files.read", {"path": ".", "query": CANARY})
    matches = json.loads(outcome.text)["matches"]

    assert outcome.decision == "ALLOW"
    assert [match["path"] for match in matches] == ["plain.txt"]


def test_an_ordinary_file_is_still_read(linked):
    outcome = linked.execute("workspace.files.read", {"path": "plain.txt"})

    assert outcome.decision == "ALLOW"
    assert "plain" in json.loads(outcome.text)["text"]
