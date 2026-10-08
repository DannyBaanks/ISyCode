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
    calls = []

    def fake(name, *, timeout=3.0):
        import time
        calls.append(name)
        time.sleep(0.02)
        from isycode.harness_probe import ProbeResult
        return ProbeResult(name, None, False, "")

    monkeypatch.setattr("isycode.harness_probe.probe_catalog_entry", fake)

    async def run():
        start = asyncio.get_running_loop().time()
        results = await probe_catalog()
        return asyncio.get_running_loop().time() - start, results

    elapsed, results = asyncio.run(run())
    assert set(results) == set(CATALOG_IDS)
    assert set(calls) == set(CATALOG_IDS)
    assert elapsed < 0.15


def test_unlock_dotfolder_requires_answered_real_directory(tmp_path):
    from isycode.harness_probe import ProbeResult

    home = tmp_path / "home"
    home.mkdir()
    real = home / ".codex"
    real.mkdir()
    link = home / ".claude"
    link.symlink_to(real, target_is_directory=True)
    assert unlock_dotfolder(ProbeResult("codex", Path("/bin/codex"), True, "Codex 1"), home=home) == real
    assert unlock_dotfolder(ProbeResult("claude", Path("/bin/claude"), True, "Claude 1"), home=home) is None
    assert unlock_dotfolder(ProbeResult("qwen", None, False, ""), home=home) is None


def test_validate_picked_root_rejects_broad_and_symlink_roots(tmp_path, monkeypatch):
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
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr("isycode.harness_probe.Path.home", classmethod(lambda cls: home))

    assert validate_picked_root(app) == app
    for candidate in (home, config, local, share, link, Path("/")):
        with pytest.raises(ValueError):
            validate_picked_root(candidate)
