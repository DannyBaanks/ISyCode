"""Hermetic self-updater tests using local Git remotes only."""
from __future__ import annotations

import subprocess
import os
from pathlib import Path

import pytest

try:
    from isycode.updater import SelfUpdater
except ImportError:
    SelfUpdater = None


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True,
                            capture_output=True, check=True)
    return result.stdout.strip()


def repositories(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "origin.git"
    repo = tmp_path / "source"
    peer = tmp_path / "peer"
    remote.mkdir()
    repo.mkdir()
    git("init", "--bare", "--initial-branch=main", str(remote), cwd=tmp_path)
    git("init", "--initial-branch=main", str(repo), cwd=tmp_path)
    git("config", "user.name", "ISyCode test", cwd=repo)
    git("config", "user.email", "isycode-test@example.invalid", cwd=repo)
    (repo / "README.md").write_text("Initial version\n", encoding="utf-8")
    git("add", "README.md", cwd=repo)
    git("commit", "-m", "initial", cwd=repo)
    git("remote", "add", "origin", str(remote), cwd=repo)
    git("push", "--set-upstream", "origin", "main", cwd=repo)
    git("clone", str(remote), str(peer), cwd=tmp_path)
    git("config", "user.name", "ISyCode test", cwd=peer)
    git("config", "user.email", "isycode-test@example.invalid", cwd=peer)
    return remote, repo, peer


def push_peer_commit(peer: Path, message: str, content: str = "Incoming version\n") -> None:
    (peer / "README.md").write_text(content, encoding="utf-8")
    git("add", "README.md", cwd=peer)
    git("commit", "-m", message, cwd=peer)
    git("push", cwd=peer)


def updater(repo: Path):
    assert SelfUpdater is not None, "SelfUpdater must exist before updater behavior can be tested"
    return SelfUpdater(source_root=repo, allow_local_remotes=True)


def test_clean_checkout_advances_only_by_fast_forward(tmp_path):
    _, repo, peer = repositories(tmp_path)
    push_peer_commit(peer, "publish update")
    before = git("rev-parse", "HEAD", cwd=repo)

    report = updater(repo).run()

    assert report.status == "updated"
    assert git("rev-parse", "HEAD", cwd=repo) != before
    assert (repo / "README.md").read_text(encoding="utf-8") == "Incoming version\n"
    assert "actualizado" in " ".join(report.lines).casefold()


def test_check_only_reports_incoming_changes_without_changing_checkout(tmp_path):
    _, repo, peer = repositories(tmp_path)
    push_peer_commit(peer, "incoming feature")
    before_head = git("rev-parse", "HEAD", cwd=repo)
    before_tree = git("write-tree", cwd=repo)
    before_content = (repo / "README.md").read_bytes()

    report = updater(repo).run(check_only=True)

    assert report.status == "available"
    assert git("rev-parse", "HEAD", cwd=repo) == before_head
    assert git("write-tree", cwd=repo) == before_tree
    assert (repo / "README.md").read_bytes() == before_content
    assert any("incoming feature" in line for line in report.lines)
    assert any("git diff" in line for line in report.lines)


@pytest.mark.parametrize("untracked", [False, True], ids=["tracked", "untracked"])
def test_dirty_checkout_is_preserved_and_never_fast_forwarded(tmp_path, untracked):
    _, repo, peer = repositories(tmp_path)
    if untracked:
        (repo / "my-notes.txt").write_text("keep me\n", encoding="utf-8")
    else:
        (repo / "README.md").write_text("my edits\n", encoding="utf-8")
    before_head = git("rev-parse", "HEAD", cwd=repo)
    local_path = repo / ("my-notes.txt" if untracked else "README.md")
    before_content = local_path.read_bytes()
    push_peer_commit(peer, "incoming feature")

    report = updater(repo).run()

    assert report.status == "dirty"
    assert git("rev-parse", "HEAD", cwd=repo) == before_head
    assert local_path.read_bytes() == before_content
    assert any("no se actualizó" in line.casefold() for line in report.lines)
    assert any(local_path.name in line for line in report.lines)


def test_diverged_branch_is_never_rewritten(tmp_path):
    _, repo, peer = repositories(tmp_path)
    (repo / "local.txt").write_text("local\n", encoding="utf-8")
    git("add", "local.txt", cwd=repo)
    git("commit", "-m", "local commit", cwd=repo)
    push_peer_commit(peer, "remote commit")
    before = git("rev-parse", "HEAD", cwd=repo)

    report = updater(repo).run()

    assert report.status == "blocked"
    assert git("rev-parse", "HEAD", cwd=repo) == before
    assert any("diverg" in line.casefold() for line in report.lines)


@pytest.mark.parametrize("url,secret", [
    ("https://github.com/another-project/tool.git", ""),
    ("https://user:private-token@github.com/DannyBaanks/ISyCode.git", "private-token"),
])
def test_unsafe_remote_is_rejected_without_echoing_url(tmp_path, url, secret):
    _, repo, _ = repositories(tmp_path)
    git("remote", "set-url", "origin", url, cwd=repo)
    before = git("rev-parse", "HEAD", cwd=repo)

    report = updater(repo).run()
    message = " ".join(report.lines)

    assert report.status == "blocked"
    assert git("rev-parse", "HEAD", cwd=repo) == before
    assert url not in message
    if secret:
        assert secret not in message


def test_fetch_failure_preserves_head_and_reports_safe_recovery(tmp_path):
    _, repo, _ = repositories(tmp_path)
    git("remote", "set-url", "origin", str(tmp_path / "missing.git"), cwd=repo)
    before = git("rev-parse", "HEAD", cwd=repo)

    report = updater(repo).run()

    assert report.status == "error"
    assert git("rev-parse", "HEAD", cwd=repo) == before
    assert any("fetch" in line.casefold() or "red" in line.casefold() for line in report.lines)


def test_missing_upstream_is_blocked_with_setup_guidance(tmp_path):
    _, repo, _ = repositories(tmp_path)
    git("branch", "--unset-upstream", cwd=repo)
    before = git("rev-parse", "HEAD", cwd=repo)

    report = updater(repo).run()

    assert report.status == "blocked"
    assert git("rev-parse", "HEAD", cwd=repo) == before
    assert any("set-upstream-to" in line for line in report.lines)


def test_local_git_filter_is_blocked_before_fetch(tmp_path):
    _, repo, _ = repositories(tmp_path)
    git("config", "filter.injected.smudge", "touch /tmp/should-not-run", cwd=repo)
    before = git("rev-parse", "HEAD", cwd=repo)

    report = updater(repo).run()

    assert report.status == "blocked"
    assert git("rev-parse", "HEAD", cwd=repo) == before
    assert any("filter" in line.casefold() or "configuración" in line.casefold()
               for line in report.lines)


def test_local_url_rewrite_is_blocked_before_fetch(tmp_path):
    _, repo, _ = repositories(tmp_path)
    git("config", "url.https://attacker.example/.insteadOf",
        "https://github.com/", cwd=repo)

    report = updater(repo).run()

    assert report.status == "blocked"
    assert any("configuración local" in line.casefold() for line in report.lines)


def test_pip_launcher_recognition_requires_exact_entry_point(tmp_path):
    assert SelfUpdater is not None
    candidate = tmp_path / "isycode"
    candidate.write_text(
        "#!/usr/bin/python3\n# -*- coding: utf-8 -*-\nimport sys\n"
        "from isycode.launcher import main\n"
        "if __name__ == '__main__':\n    sys.exit(main())\n",
        encoding="utf-8",
    )
    assert SelfUpdater._is_generated_pip_launcher(candidate)
    candidate.write_text(
        "#!/usr/bin/python3\nimport os\nos.system('touch /tmp/not-okay')\n"
        "from isycode.launcher import main\n"
        "if __name__ == '__main__':\n    sys.exit(main())\n",
        encoding="utf-8",
    )
    assert not SelfUpdater._is_generated_pip_launcher(candidate)


def test_incoming_file_cannot_overwrite_an_ignored_local_file(tmp_path):
    remote, repo, peer = repositories(tmp_path)
    (repo / ".gitignore").write_text("cache/\n", encoding="utf-8")
    git("add", ".gitignore", cwd=repo)
    git("commit", "-m", "ignore local cache", cwd=repo)
    git("push", cwd=repo)
    git("fetch", "origin", "main", cwd=peer)
    git("merge", "--ff-only", "FETCH_HEAD", cwd=peer)
    cache = repo / "cache"
    cache.mkdir()
    ignored = cache / "generated.txt"
    ignored.write_text("preserve this ignored user file\n", encoding="utf-8")
    incoming = peer / "cache"
    incoming.mkdir()
    remote_path = incoming / "generated.txt"
    remote_path.write_text("incoming tracked file\n", encoding="utf-8")
    git("add", "-f", "cache/generated.txt", cwd=peer)
    git("commit", "-m", "add cache data", cwd=peer)
    git("push", cwd=peer)
    before = git("rev-parse", "HEAD", cwd=repo)

    report = updater(repo).run()

    assert report.status == "dirty"
    assert git("rev-parse", "HEAD", cwd=repo) == before
    assert ignored.read_text(encoding="utf-8") == "preserve this ignored user file\n"


def bootstrap_repository(tmp_path: Path) -> Path:
    remote = tmp_path / "bootstrap.git"
    seed = tmp_path / "seed"
    remote.mkdir()
    seed.mkdir()
    git("init", "--bare", "--initial-branch=main", str(remote), cwd=tmp_path)
    git("init", "--initial-branch=main", str(seed), cwd=tmp_path)
    git("config", "user.name", "ISyCode test", cwd=seed)
    git("config", "user.email", "isycode-test@example.invalid", cwd=seed)
    (seed / "pyproject.toml").write_text("[project]\nname='isycode'\n", encoding="utf-8")
    launcher = seed / "scripts" / "isycode"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    git("add", ".", cwd=seed)
    git("commit", "-m", "bootstrap source", cwd=seed)
    git("remote", "add", "origin", str(remote), cwd=seed)
    git("push", "--set-upstream", "origin", "main", cwd=seed)
    return remote


def no_checkout_updater(data_home: Path, remote: Path, runner=subprocess.run):
    assert SelfUpdater is not None
    return SelfUpdater(source_root=None, discover_source_checkout=False, data_home=data_home,
                       official_repository=str(remote), command_runner=runner,
                       allow_local_remotes=True)


def test_bootstrap_check_only_does_not_create_installation(tmp_path):
    remote = bootstrap_repository(tmp_path)
    data_home = tmp_path / "data"

    report = no_checkout_updater(data_home, remote).run(check_only=True)

    assert report.status == "available"
    assert not (data_home / "isycode").exists()
    assert any("no clonó" in line.casefold() for line in report.lines)


def test_bootstrap_preserves_non_git_destination(tmp_path):
    remote = bootstrap_repository(tmp_path)
    data_home = tmp_path / "data"
    destination = data_home / "isycode" / "source"
    destination.mkdir(parents=True)
    note = destination / "keep.txt"
    note.write_text("user data\n", encoding="utf-8")

    report = no_checkout_updater(data_home, remote).run()

    assert report.status == "blocked"
    assert note.read_text(encoding="utf-8") == "user data\n"
    assert any(str(destination) in line for line in report.lines)


def test_bootstrap_installs_source_without_replacing_foreign_launcher(tmp_path, monkeypatch):
    remote = bootstrap_repository(tmp_path)
    data_home = tmp_path / "data"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    foreign = home / ".local" / "bin" / "isycode"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("another application\n", encoding="utf-8")

    def runner(args, **kwargs):
        if args[1:3] == ["-m", "venv"]:
            python = Path(args[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            python.chmod(0o755)
            return subprocess.CompletedProcess(args, 0, "", "")
        if "-m" in args and "pip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.run(args, **kwargs)

    report = no_checkout_updater(data_home, remote, runner).run()
    destination = data_home / "isycode" / "source"

    assert report.status == "updated"
    assert (destination / "scripts" / "isycode").is_file()
    assert (destination / ".venv" / "bin" / "python").is_file()
    assert foreign.read_text(encoding="utf-8") == "another application\n"
    assert any(str(destination / "scripts" / "isycode") in line for line in report.lines)
