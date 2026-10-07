"""Shell-free Multi Harness CLI probes and root validation."""
from __future__ import annotations

import asyncio
import os
import signal
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from isycode.harness_graph import CATALOG_IDS
from isycode.workspace_setup import broad_workspace_reason


@dataclass(frozen=True)
class HarnessCatalogEntry:
    harness_id: str
    executables: tuple[str, ...]
    dotfolder: str
    # Extra environment for the `--version` probe only. Some CLIs self-update
    # when run; the probe must stay read-only, so they get their opt-out here.
    probe_env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    harness_id: str
    executable: Path | None
    answered: bool
    version_line: str


CATALOG: dict[str, HarnessCatalogEntry] = {
    "crush": HarnessCatalogEntry("crush", ("crush",), ".crush"),
    "qwen": HarnessCatalogEntry("qwen", ("qwen",), ".qwen"),
    "opencode": HarnessCatalogEntry("opencode", ("opencode",), ".opencode"),
    "claude": HarnessCatalogEntry("claude", ("claude",), ".claude"),
    "codex": HarnessCatalogEntry("codex", ("codex",), ".codex"),
    "grok": HarnessCatalogEntry("grok", ("grok",), ".grok"),
    "hermes": HarnessCatalogEntry("hermes", ("hermes",), ".hermes"),
    "fx": HarnessCatalogEntry("fx", ("fx",), ".fx"),
    "openclaw": HarnessCatalogEntry("openclaw", ("openclaw",), ".openclaw"),
    "pi": HarnessCatalogEntry("pi", ("pi",), ".pi"),
    "kimi": HarnessCatalogEntry("kimi", ("kimi",), ".kimi-code"),
    "cursor": HarnessCatalogEntry("cursor", ("cursor-agent", "cursor"), ".cursor"),
    "copilot": HarnessCatalogEntry("copilot", ("copilot",), ".copilot"),
    # `command-code --version` installs pending updates (1.74.1 -> 1.77.0 seen
    # 2026-10-07); COMMANDCODE_SKIP_UPDATES gates both its check and its apply.
    "commandcode": HarnessCatalogEntry(
        "commandcode", ("command-code",), ".commandcode",
        probe_env=(("COMMANDCODE_SKIP_UPDATES", "1"),),
    ),
    "kilo": HarnessCatalogEntry("kilo", ("kilo", "kilocode"), ".config/kilo"),
}

if tuple(CATALOG) != CATALOG_IDS:  # checked-in data must not silently reorder the UI.
    raise RuntimeError("Multi Harness catalog order drifted")


def _resolved_executable(name: str) -> Path | None:
    found = shutil.which(name)
    if not found:
        return None
    try:
        path = Path(found).resolve(strict=True)
        info = path.stat()
    except (OSError, RuntimeError):
        return None
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        return None
    return path


def _public_version_line(output: bytes) -> str:
    try:
        text = output.decode("utf-8", errors="strict")
    except UnicodeError:
        return ""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        return ""
    first = first[:120]
    if "@" in first or (" " not in first and len(first) > 80):
        return ""
    return first


def _run_probe(path: Path, *, timeout: float, env: tuple[tuple[str, str], ...] = ()) -> tuple[bool, str]:
    if timeout <= 0 or timeout > 10:
        raise ValueError("probe timeout is outside the allowed range")
    process = None
    try:
        process = subprocess.Popen(
            [str(path), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            env={**os.environ, **dict(env)} if env else None,
            start_new_session=(os.name == "posix"),
        )
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                elif process.poll() is None:
                    process.kill()
            except ProcessLookupError:
                pass
            # A child may have inherited stdout, even after the probed CLI
            # exits. Never wait indefinitely for that pipe to close.
            try:
                process.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                if process.stdout is not None:
                    process.stdout.close()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
        return False, ""
    except OSError:
        return False, ""
    if process.returncode != 0 or len(output) > 4096:
        return False, ""
    line = _public_version_line(output)
    return bool(line), line


def probe_one(executable_name: str, *, timeout: float = 3.0) -> ProbeResult:
    """Probe one executable name with exactly `--version`, never a shell."""
    path = _resolved_executable(executable_name)
    if path is None:
        return ProbeResult(executable_name, None, False, "")
    answered, line = _run_probe(path, timeout=timeout)
    return ProbeResult(executable_name, path, answered, line)


def probe_catalog_entry(harness_id: str, *, timeout: float = 3.0) -> ProbeResult:
    entry = CATALOG.get(harness_id)
    if entry is None:
        raise ValueError("unknown harness id")
    for executable_name in entry.executables:
        path = _resolved_executable(executable_name)
        if path is None:
            continue
        answered, line = _run_probe(path, timeout=timeout, env=entry.probe_env)
        # Cursor probes only the first executable found on PATH, even if it fails.
        return ProbeResult(harness_id, path, answered, line)
    return ProbeResult(harness_id, None, False, "")


async def probe_catalog(*, timeout: float = 3.0) -> dict[str, ProbeResult]:
    """Probe all catalog harnesses concurrently on worker threads."""
    results = await asyncio.gather(*(
        asyncio.to_thread(probe_catalog_entry, harness_id, timeout=timeout)
        for harness_id in CATALOG_IDS
    ))
    return {result.harness_id: result for result in results}


def unlock_dotfolder(result: ProbeResult, *, home: Path | None = None) -> Path | None:
    if not result.answered or result.harness_id not in CATALOG:
        return None
    base = Path(home) if home is not None else Path.home()
    candidate = base / CATALOG[result.harness_id].dotfolder
    try:
        info = candidate.lstat()
        if not stat.S_ISDIR(info.st_mode) or candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        if resolved != candidate.absolute():
            return None
    except (OSError, RuntimeError):
        return None
    return resolved


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def validate_picked_root(candidate: Path) -> Path:
    """Validate one explicit harness root without granting workspace authority."""
    try:
        lexical = Path(os.path.abspath(os.fspath(candidate.expanduser())))
        os.fspath(lexical).encode("utf-8", errors="strict")
        info = lexical.lstat()
        if not stat.S_ISDIR(info.st_mode) or _has_symlink_component(lexical):
            raise ValueError("selected root must be a real directory without symlinks")
        resolved = lexical.resolve(strict=True)
        if resolved != lexical:
            raise ValueError("selected root changed while resolving")
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        raise ValueError("selected harness folder is unavailable or unsafe") from exc

    home = Path.home().expanduser().resolve(strict=True)
    rejected = {home, home / ".config", home / ".local", home / ".local" / "share"}
    if resolved in rejected or resolved == Path(resolved.anchor) or resolved in home.parents:
        raise ValueError("selected harness folder is too broad")
    # broad_workspace_reason also rejects temp roots and mount points.
    if broad_workspace_reason(resolved) is not None:
        raise ValueError("selected harness folder is too broad")
    return resolved


__all__ = [
    "CATALOG", "HarnessCatalogEntry", "ProbeResult", "probe_catalog", "probe_catalog_entry",
    "probe_one", "unlock_dotfolder", "validate_picked_root",
]
