"""Content search is a bounded, descriptor-safe read through the read owner."""
import json
import os
from pathlib import Path

import pytest

from isycode.action_runtime import LocalWorkspaceReadOwner, TOOL_ACTIONS
from isycode.workspace_authority import WorkspaceAuthority

pytestmark = pytest.mark.skipif(os.name == "nt", reason="descriptor-safe reads are POSIX-only")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def parse_config():\n    return PARSE_CONFIG\n")
    (root / "src" / "util.py").write_text("import app\napp.parse_config()\n")
    (root / ".env").write_text("SECRET=parse_config\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "lib.js").write_text("parse_config()\n")
    (root / "blob.bin").write_bytes(b"\0\1parse_config\0")
    outside = tmp_path / "outside.txt"
    outside.write_text("parse_config outside\n")
    (root / "link.py").symlink_to(outside)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    return LocalWorkspaceReadOwner(root, authority), authority, root.resolve()


def _grep(owner, query, path="."):
    return owner.execute("workspace.files.read", {"query": query, "path": path})


def test_grep_is_a_read_and_needs_the_read_grant(repo):
    owner, _, _ = repo
    assert TOOL_ACTIONS["workspace_grep"] == "workspace.files.read"
    assert _grep(owner, "parse_config").decision == "DENY"


def test_grep_finds_lines_and_skips_sensitive_binary_dependency_and_linked_files(repo):
    owner, authority, root = repo
    authority.set_mode("classic")
    outcome = _grep(owner, "PARSE_CONFIG")
    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    matches = json.loads(outcome.text)["matches"]
    assert {(m["path"], m["line"]) for m in matches} == {
        ("src/app.py", 1), ("src/app.py", 2), ("src/util.py", 2)}


def test_grep_can_target_one_file(repo):
    owner, authority, _ = repo
    authority.set_mode("classic")
    matches = json.loads(_grep(owner, "import", "src/util.py").text)["matches"]
    assert matches == [{"path": "src/util.py", "line": 1, "text": "import app"}]


@pytest.mark.parametrize("query", ["", "   ", "x" * 257])
def test_grep_rejects_empty_or_huge_queries(repo, query):
    owner, authority, _ = repo
    authority.set_mode("classic")
    assert _grep(owner, query).decision == "ERROR"


def test_grep_cannot_leave_the_workspace(repo):
    owner, authority, _ = repo
    authority.set_mode("classic")
    assert _grep(owner, "parse", "../outside.txt").decision == "DENY"


def test_search_and_grep_handle_large_repos_bfs_and_skip_worktrees(repo):
    owner, authority, root = repo
    authority.set_mode("classic")
    for skipped_dir in (".worktrees", ".codex-worktrees", ".venv-linux", "pkg.egg-info"):
        heavy = root / skipped_dir / "deep"
        heavy.mkdir(parents=True)
        for i in range(50):
            (heavy / f"ignored_{i}.yml").write_text("PARSE_CONFIG in worktree\n")
    for idx in range(350):
        sub = root / f"repo_{idx:03d}" / ".github" / "workflows"
        sub.mkdir(parents=True)
        if idx in (0, 175, 349):
            (sub / "ci.yml").write_text("name: CI\non: push\n")

    search_outcome = owner.execute("workspace.files.search", {"query": ".github/workflows", "path": "/"})
    assert search_outcome.decision == "ALLOW"
    search_payload = json.loads(search_outcome.text)
    assert search_payload["truncated"] is False
    assert search_payload["directories_scanned"] > 300
    assert len(search_payload["matches"]) == 353

    file_search = json.loads(
        owner.execute("workspace.files.search", {"query": "ci.yml", "path": "/"}).text
    )
    assert file_search["truncated"] is False
    assert {m["path"] for m in file_search["matches"]} == {
        "repo_000/.github/workflows/ci.yml",
        "repo_175/.github/workflows/ci.yml",
        "repo_349/.github/workflows/ci.yml",
    }

    grep_payload = json.loads(_grep(owner, "PARSE_CONFIG", "/").text)
    assert grep_payload["truncated"] is False
    assert all(not m["path"].startswith((".worktrees", ".codex-worktrees", ".venv-linux", "pkg.egg-info"))
               for m in grep_payload["matches"])


def test_list_sorts_directories_before_cap_and_output_limit_keeps_valid_json(repo):
    owner, authority, root = repo
    authority.set_mode("classic")
    big_dir = root / "big"
    big_dir.mkdir()
    for i in range(1100):
        (big_dir / f"file_{i:04d}.txt").write_text(f"line {i}\n")
    (big_dir / "zzz_subdir").mkdir()

    list_outcome = owner.execute("workspace.files.list", {"path": "big"})
    assert list_outcome.decision == "ALLOW"
    listed = json.loads(list_outcome.text)
    assert listed["entries"][0] == {"name": "zzz_subdir", "kind": "directory"}
    assert len(listed["entries"]) == 1101

    large_file = root / "src" / "large.txt"
    large_file.write_text("A" * 40_000)
    read_outcome = owner.execute("workspace.files.read", {"path": "src/large.txt"})
    assert read_outcome.decision == "ALLOW"
    parsed_read = json.loads(read_outcome.text)
    assert parsed_read["path"] == "src/large.txt"
    assert parsed_read["truncated"] is True
    assert "[output truncated]" in parsed_read["text"]
