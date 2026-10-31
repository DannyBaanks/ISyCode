import asyncio
import os
import time
from pathlib import Path

import pytest

from isycode.harness_graph import CATALOG_IDS
from isycode.harness_probe import (
    CATALOG,
    probe_catalog,
    probe_one,
    unlock_dotfolder,
    validate_picked_root,
)


def _exe(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.skipif(os.name != "posix", reason="POSIX shell fixture; Windows probe has a native argv test")
def test_probe_one_uses_version_argv_and_rejects_timeout_and_private_lines(tmp_path, monkeypatch):
    ok = _exe(tmp_path / "ok", 'test "$1" = "--version" || exit 9; echo "Tool 1.2.3"')
    private = _exe(tmp_path / "private", 'echo "user@example.com"')
    slow = _exe(tmp_path / "slow", 'sleep 2; echo "Slow 1"')
    monkeypatch.setattr("isycode.harness_probe.shutil.which",
                        lambda name: str({"ok": ok, "private": private, "slow": slow}.get(name, "")) or None)

    assert probe_one("ok", timeout=0.5).answered is True
    assert probe_one("ok", timeout=0.5).version_line == "Tool 1.2.3"
    assert probe_one("private", timeout=0.5).answered is False
    assert probe_one("missing", timeout=0.5).answered is False
    assert probe_one("slow", timeout=0.05).answered is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX shell fixture; Windows probe has a native environment test")
def test_probe_env_reaches_only_the_entry_that_declares_it(tmp_path, monkeypatch):
    # command-code self-updates on --version unless COMMANDCODE_SKIP_UPDATES is set
    exe = _exe(tmp_path / "cc", 'test "$COMMANDCODE_SKIP_UPDATES" = "1" && echo "Safe 1" || echo "Unsafe 1"')
    monkeypatch.setattr("isycode.harness_probe.shutil.which", lambda name: str(exe))
    monkeypatch.delenv("COMMANDCODE_SKIP_UPDATES", raising=False)
    from isycode.harness_probe import probe_catalog_entry

    assert CATALOG["commandcode"].probe_env == (("COMMANDCODE_SKIP_UPDATES", "1"),)
    assert probe_catalog_entry("commandcode", timeout=2).version_line == "Safe 1"
    assert probe_catalog_entry("codex", timeout=2).version_line == "Unsafe 1"
    assert "COMMANDCODE_SKIP_UPDATES" not in os.environ


@pytest.mark.skipif(os.name != "posix", reason="POSIX shell process-tree fixture")
def test_probe_timeout_does_not_wait_for_child_holding_stdout(tmp_path, monkeypatch):
    inherited_pipe = _exe(tmp_path / "inherited-pipe", "sleep 5 & exit 0")
    monkeypatch.setattr("isycode.harness_probe.shutil.which", lambda name: str(inherited_pipe))
    started = time.monotonic()
    assert probe_one("inherited-pipe", timeout=0.05).answered is False
    assert time.monotonic() - started < 2


def test_catalog_has_reviewed_cursor_fallback_and_kimi_folder():
    assert tuple(CATALOG) == CATALOG_IDS
    assert CATALOG["cursor"].executables == ("cursor-agent", "cursor")
    assert CATALOG["kimi"].dotfolder == ".kimi-code"
    assert CATALOG["kilo"].executables == ("kilo", "kilocode")
    assert CATALOG["kilo"].dotfolder == ".config/kilo"
    assert "agent" not in CATALOG


def test_probe_catalog_checks_all_entries_concurrently(monkeypatch):
    span = {}

    def fake(name, *, timeout=3.0):
        import time
        from isycode.harness_probe import ProbeResult
        span[name] = [time.monotonic(), None]
        time.sleep(0.02)
        span[name][1] = time.monotonic()
        return ProbeResult(name, None, False, "")

    monkeypatch.setattr("isycode.harness_probe.probe_catalog_entry", fake)

    results = asyncio.run(probe_catalog())
    assert set(results) == set(CATALOG_IDS)
    assert set(span) == set(CATALOG_IDS)
    # A wall-clock bound loses on a loaded runner and says nothing about the
    # code. Concurrency has a shape: with a small thread pool not every probe
    # can start at once, but at least two must be in flight together. A
    # serialized roster shows zero overlap.
    windows = [(start, finish) for start, finish in span.values()]
    overlapping = sum(1 for index, (a_start, _) in enumerate(windows)
                      for (b_start, b_finish) in windows[index + 1:]
                      if a_start < b_finish and b_start < windows[index][1])
    assert overlapping, "no two probes ran at the same time"


def test_unlock_dotfolder_requires_answered_real_directory(tmp_path, make_directory_link):
    from isycode.harness_probe import ProbeResult

    home = tmp_path / "home"
    home.mkdir()
    real = home / ".codex"
    real.mkdir()
    link = home / ".claude"
    make_directory_link(link, real)
    assert unlock_dotfolder(ProbeResult("codex", Path("/bin/codex"), True, "Codex 1"), home=home) == real
    assert unlock_dotfolder(ProbeResult("claude", Path("/bin/claude"), True, "Claude 1"), home=home) is None
    assert unlock_dotfolder(ProbeResult("qwen", None, False, ""), home=home) is None


def test_validate_picked_root_rejects_broad_and_symlink_roots(tmp_path, monkeypatch, make_directory_link):
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".config"
    config.mkdir()
    local = home / ".local"
    local.mkdir()
    share = local / "share"
    share.mkdir()
    app = config / "opencode"
    app.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    make_directory_link(link, real)
    monkeypatch.setattr("isycode.harness_probe.Path.home", classmethod(lambda cls: home))

    assert validate_picked_root(app) == app
    for candidate in (home, config, local, share, link, Path("/")):
        with pytest.raises(ValueError):
            validate_picked_root(candidate)


@pytest.mark.skipif(os.name != "nt", reason="Windows executable discovery contract")
def test_windows_probe_uses_shell_free_version_argv_and_scoped_environment(tmp_path, monkeypatch):
    executable = tmp_path / "command-code.exe"
    executable.write_bytes(b"synthetic executable placeholder")
    calls = []

    class Process:
        returncode = 0

        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))

        def communicate(self, timeout):
            return b"Safe 1\r\n", None

    monkeypatch.setattr("isycode.harness_probe.shutil.which", lambda name: str(executable))
    monkeypatch.setattr("isycode.harness_probe.subprocess.Popen", Process)
    monkeypatch.delenv("COMMANDCODE_SKIP_UPDATES", raising=False)
    from isycode.harness_probe import probe_catalog_entry

    result = probe_catalog_entry("commandcode", timeout=2)
    assert result.answered and result.version_line == "Safe 1"
    argv, kwargs = calls[0]
    assert argv == [str(executable.resolve()), "--version"]
    assert kwargs["shell"] is False
    assert kwargs["env"]["COMMANDCODE_SKIP_UPDATES"] == "1"
    assert "COMMANDCODE_SKIP_UPDATES" not in os.environ
