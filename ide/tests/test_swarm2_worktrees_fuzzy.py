"""Tests for Git worktrees, 8-tier fuzzy matcher, QuickOpenDialog, Git watcher & async GitHub scan."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt

from core.fuzzy import (
    TIER_ACRONYM,
    TIER_CASE_INSENSITIVE_EXACT,
    TIER_EMPTY_QUERY,
    TIER_EXACT,
    TIER_PREFIX,
    TIER_SUBSEQUENCE,
    TIER_SUBSTRING,
    TIER_WORD_BOUNDARY,
    fuzzy_score,
    matched_ranges,
    normalize,
    rank_candidates,
)
from core.worktrees import WorktreeError, WorktreeManager, parse_worktree_list
from ui.app import AppController
from ui.main_window import MainWindow
from ui.palette import Command, QuickOpenDialog
from ui.panels.workspace import WorkspacePanel
from ui.panels.worktrees import WorktreesPanel


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


# ---------------------------------------------------------------------------
# 1. core/fuzzy.py — 8-tier ranking & matched ranges
# ---------------------------------------------------------------------------

def test_fuzzy_tier_ordering_and_ranking():
    s_exact = fuzzy_score("main.py", "main.py")
    s_ci_exact = fuzzy_score("MAIN.PY", "main.py")
    s_prefix = fuzzy_score("main", "main.py")
    s_word = fuzzy_score("read", "file_read.py")
    s_camel = fuzzy_score("fm", "FileManager")
    s_substr = fuzzy_score("ain", "main.py")
    s_subseq = fuzzy_score("mny", "main.py")
    s_empty = fuzzy_score("", "main.py")

    assert s_exact > s_ci_exact > s_prefix > s_word > s_camel > s_substr > s_subseq > s_empty
    assert s_exact // 1000 == TIER_EXACT == 8
    assert s_ci_exact // 1000 == TIER_CASE_INSENSITIVE_EXACT == 7
    assert s_prefix // 1000 == TIER_PREFIX == 6
    assert s_word // 1000 == TIER_WORD_BOUNDARY == 5
    assert s_camel // 1000 == TIER_ACRONYM == 4
    assert s_substr // 1000 == TIER_SUBSTRING == 3
    assert s_subseq // 1000 == TIER_SUBSEQUENCE == 2
    assert s_empty // 1000 == TIER_EMPTY_QUERY == 1
    assert fuzzy_score("zzz", "main.py") is None

    # Accent-insensitive normalization
    assert normalize("Árbol") == "arbol"
    assert fuzzy_score("arbol", "Árbol.py") is not None

    # Ranking places exact & prefix before deeper matches
    candidates = ["src/sub/main_helper.py", "main.py", "src/main.py", "unrelated.txt"]
    ranked = rank_candidates("main.py", candidates)
    assert ranked[0] == "main.py"
    assert "unrelated.txt" not in ranked

    # Matched ranges
    assert matched_ranges("main", "src/main.py") == [(4, 8)]
    assert matched_ranges("zzz", "src/main.py") == []


# ---------------------------------------------------------------------------
# 2. core/worktrees.py — parse, list, add (with start_point), preflight, remove
# ---------------------------------------------------------------------------

def test_parse_worktree_list_porcelain():
    sample = (
        "worktree /tmp/repo\n"
        "HEAD 1111111111111111111111111111111111111111\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /tmp/repo-wt\n"
        "HEAD 2222222222222222222222222222222222222222\n"
        "detached\n"
        "locked working on release\n"
    )
    items = parse_worktree_list(sample)
    assert len(items) == 2
    assert items[0].branch == "main" and items[0].name == "main"
    assert items[1].detached is True and items[1].locked is True
    assert items[1].lock_reason == "working on release"


def test_worktree_manager_add_preflight_and_safe_remove(git_repo: Path):
    mgr = WorktreeManager(git_repo)
    initial = asyncio.run(mgr.list_worktrees())
    assert len(initial) == 1
    assert initial[0].branch == "main"

    # Add worktree with explicit start_point
    wt_path = git_repo.parent / "repo-feat"
    created = asyncio.run(mgr.add_worktree(wt_path, "feat/demo", create_branch=True, start_point="HEAD"))
    assert Path(created.path).resolve() == wt_path.resolve()
    assert created.branch == "feat/demo"

    # Clean preflight is safe
    clean_report = asyncio.run(mgr.preflight_remove(wt_path))
    assert clean_report.safe is True
    assert clean_report.warnings() == []

    # Untracked file blocks removal unless force=True
    (wt_path / "draft.txt").write_text("unsaved work", encoding="utf-8")
    dirty_report = asyncio.run(mgr.preflight_remove(wt_path))
    assert dirty_report.safe is False
    assert "draft.txt" in dirty_report.untracked

    with pytest.raises(WorktreeError, match="conservó"):
        asyncio.run(mgr.remove_worktree(wt_path, force=False))
    assert wt_path.exists()

    # Force removal succeeds
    removed_report = asyncio.run(mgr.remove_worktree(wt_path, force=True))
    assert removed_report.safe is False
    assert not wt_path.exists()


# ---------------------------------------------------------------------------
# 3. ui/palette.py — QuickOpenDialog files & `>` command mode
# ---------------------------------------------------------------------------

def test_quick_open_dialog_files_and_command_mode(qtbot, tmp_path: Path):
    (tmp_path / "main.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "utils.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    opened: list[str] = []
    ran: list[str] = []
    dlg = QuickOpenDialog(
        tmp_path,
        on_open_file=opened.append,
        actions=[Command("cmd_hello", "Say Hello", lambda: ran.append("hello"), "greet")],
    )
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: not dlg._scan_timer.isActive(), timeout=3000)

    assert dlg.file_count() == 2
    dlg.input.setText("main")
    assert dlg.results.count() >= 1
    # Item text must be clean plain text, never literal <b> tags
    assert dlg.results.item(0).text() == "main.py"
    assert "<b>" not in dlg.results.item(0).text()
    dlg._activate_current()
    assert opened == [str((tmp_path / "main.py").resolve())]

    # Command mode with `>`
    dlg.input.setText(">hello")
    assert dlg.results.count() == 1
    assert dlg.results.item(0).text() == "Say Hello"
    dlg._activate_current()
    assert ran == ["hello"]


# ---------------------------------------------------------------------------
# 4. ui/panels/workspace.py — debounced QFileSystemWatcher on .git/HEAD & index
# ---------------------------------------------------------------------------

def test_workspace_git_watcher_emits_debounced_signal(qtbot, git_repo: Path):
    panel = WorkspacePanel()
    panel.GIT_WATCH_DEBOUNCE_MS = 40
    panel._git_debounce.setInterval(40)
    qtbot.addWidget(panel)
    panel.set_root(git_repo)

    watched = panel.git_watched_paths()
    assert any(p.endswith("HEAD") for p in watched)
    assert any(p.endswith("index") for p in watched)

    signals = []
    panel.git_state_changed.connect(lambda: signals.append(True))

    # Trigger a real HEAD change via git checkout -b
    _git(git_repo, "checkout", "-b", "watched-branch")
    qtbot.waitUntil(lambda: len(signals) >= 1, timeout=3000)
    assert len(signals) >= 1
    panel.stop_watching_git()


# ---------------------------------------------------------------------------
# 5. ui/panels/github.py — auto_discover_folders uses async subprocess (no subprocess.run)
# ---------------------------------------------------------------------------

def test_github_auto_discover_uses_async_subprocess():
    import ast
    src = Path(__file__).resolve().parent.parent.joinpath("ui", "panels", "github.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    ]
    assert "subprocess.run" not in calls
    assert "asyncio.create_subprocess_exec" in calls


# ---------------------------------------------------------------------------
# 6. ui/panels/worktrees.py & ui/main_window.py integration
# ---------------------------------------------------------------------------

def test_worktrees_panel_and_main_window_wiring(qtbot, git_repo: Path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: git_repo.parent)
    wt_path = git_repo.parent / "repo-linked"
    _git(git_repo, "worktree", "add", "-b", "linked", str(wt_path))

    controller = AppController(git_repo)
    win = MainWindow(controller=controller)
    qtbot.addWidget(win)

    # WorktreesPanel is wired into Status grouped tabs
    assert win.worktrees_panel is not None
    assert "Worktrees" in [p.title() for p in win.panel_bar.panels()]
    qtbot.waitUntil(lambda: len(win.worktrees_panel.worktrees()) == 2, timeout=4000)

    # Selecting main disables remove; selecting linked enables remove and emits open signal
    win.worktrees_panel.list.setCurrentRow(0)
    assert not win.worktrees_panel.remove_btn.isEnabled()
    win.worktrees_panel.list.setCurrentRow(1)
    assert win.worktrees_panel.remove_btn.isEnabled()

    requested = []
    win.worktrees_panel.worktree_open_requested.connect(requested.append)
    win.worktrees_panel.open_selected()
    assert requested == [str(wt_path.resolve())]

    # Ctrl+P opens QuickOpenDialog; Ctrl+Shift+P is registered for Providers
    shortcut_keys = {sc.key().toString() for sc in win._shortcuts}
    assert "Ctrl+P" in shortcut_keys
    assert "Ctrl+Shift+P" in shortcut_keys

    dlg = win.open_quick_open()
    assert isinstance(dlg, QuickOpenDialog)
    dlg.close()

    win.close()
