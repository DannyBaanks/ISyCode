"""Read-only peer claims from a grit registry the user runs on this workspace.

grit (https://github.com/rtk-ai/grit, Apache-2.0) is an external tool that
other AI agents use to lock AST symbols before editing. ISyCode never claims,
merges, creates worktrees or changes any Sentinel decision here; it only
reads the registry the user created with ``grit init`` and shows the claims
touching one file as an advisory note. The feature is opt-in: it needs the
grit binary on PATH, a ``.grit`` registry in the workspace root, an explicit
``grit.claims.read`` grant and a ``workspace.files.read`` grant for the root.

The pinned binary runs inside the same bubblewrap profile as the LSP
adapters: no network (seccomp), no home, workspace mounted read-only — only
``.grit`` stays writable because SQLite opens its registry in WAL mode,
which writes ``-wal``/``-shm`` sidecar files even for readers. grit output
is untrusted text; the parser accepts only the exact grammar of the pinned
build and rejects anything else.
"""
from __future__ import annotations

import asyncio
import ctypes.util
import hashlib
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any

from isycode.lsp import network_deny_bootstrap

GRIT_ID = "grit"
GRIT_LABEL = "grit peer claims"
MAX_STATUS_BYTES = 64 * 1024
MAX_CLAIMS = 64
MAX_FIELD_CHARS = 200
STATUS_TIMEOUT_S = 5.0

_AGENT_LINE = re.compile(r"^\* (?P<agent>.+?) -- (?P<intent>.+?)$")
# "  | src/auth.py::login (read) (2026-10-09 09:40:18) [ttl=600s]" (pinned format)
_CLAIM_LINE = re.compile(
    r"^\s*\|\s+(?P<symbol>\S+?)(?P<read>\s+\(read\))?\s+\((?P<locked_at>[^()]*)\)"
    r"\s+\[(?P<state>[^\]]*)\]\s*$")
_TOTAL_LINE = re.compile(r"^\d+/\d+ symbols locked(, \d+ queued)?$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_grit() -> dict[str, Any] | None:
    """Locate the user's grit binary without starting it (mirrors LSP discovery)."""
    command = shutil.which(GRIT_ID)
    if not command:
        return None
    try:
        executable = Path(command).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return None
    try:
        digest = _sha256_file(executable)
    except OSError:
        return None
    bwrap = shutil.which("bwrap")
    sandbox = str(Path(bwrap).resolve(strict=True)) if bwrap else ""
    ready = bool(sandbox and ctypes.util.find_library("seccomp"))
    return {
        "id": GRIT_ID,
        "label": GRIT_LABEL,
        "state": "sandbox_ready" if ready else "installed_unavailable",
        "command": command,
        "executable": str(executable),
        "sha256": digest,
        "sandbox_executable": sandbox,
        "capability": "claims/status",
        "repository": "https://github.com/rtk-ai/grit",
    }


def has_grit_registry(root: Path) -> bool:
    """True when the user initialized grit in this workspace (``.grit`` directory)."""
    try:
        return stat.S_ISDIR((root / ".grit").stat().st_mode)
    except OSError:
        return False


def _sandbox_command(root: Path, info: dict[str, Any]) -> list[str]:
    sandbox = str(Path(info["sandbox_executable"]).resolve(strict=True))
    executable = Path(info["executable"]).resolve(strict=True)
    root = root.resolve(strict=True)
    registry = root / ".grit"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("grit executable is unavailable")
    if not root.is_dir() or not registry.is_dir():
        raise RuntimeError("grit registry is unavailable in the workspace")
    # Same profile as the LSP adapters: no network namespace content, seccomp
    # socket denial, no home, read-only OS files. The workspace stays
    # read-only except .grit: SQLite needs to write its WAL sidecar files
    # even for a status read.
    args = [sandbox, "--die-with-parent", "--unshare-all", "--share-net",
            "--clearenv", "--ro-bind", "/usr", "/usr"]
    for source, destination, alias in (("/bin", "/bin", "/usr/bin"),
                                       ("/lib", "/lib", "/usr/lib"),
                                       ("/lib64", "/lib64", "/usr/lib64")):
        if Path(source).is_symlink():
            args.extend(["--symlink", alias, destination])
        elif Path(source).exists():
            args.extend(["--ro-bind", source, destination])
    args.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                "--dir", "/runtime", "--dir", "/workspace",
                "--ro-bind", str(executable), "/runtime/grit",
                "--ro-bind", str(root), "/workspace",
                "--bind", str(registry), "/workspace/.grit",
                "--chdir", "/workspace",
                "--setenv", "HOME", "/tmp", "--setenv", "XDG_CONFIG_HOME", "/tmp/config",
                "--setenv", "NO_COLOR", "1",
                "--setenv", "PATH", "/usr/bin:/bin:/runtime",
                "--", "/usr/bin/python3", "-I", "-c", network_deny_bootstrap(16),
                "/runtime/grit", "status"])
    return args


def parse_status(text: str) -> list[dict[str, str]]:
    """Parse the pinned ``grit status`` grammar strictly; anything else is an error."""
    claims: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    lines = text.splitlines()
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if lines == ["No active locks."]:
        return claims
    for line in lines:
        if not line.strip():
            continue  # blank separator lines (e.g. before the totals line)
        total = _TOTAL_LINE.match(line)
        if total:
            continue
        agent = _AGENT_LINE.match(line)
        if agent:
            current = {"agent": agent.group("agent")[:MAX_FIELD_CHARS],
                       "intent": agent.group("intent")[:MAX_FIELD_CHARS]}
            continue
        claim = _CLAIM_LINE.match(line)
        if claim and current is not None:
            if len(claims) >= MAX_CLAIMS:
                break
            claims.append({"agent": current["agent"], "intent": current["intent"],
                           "symbol": claim.group("symbol")[:MAX_FIELD_CHARS],
                           "mode": "read" if claim.group("read") else "write",
                           "locked_at": claim.group("locked_at")[:MAX_FIELD_CHARS]})
            continue
        raise ValueError("unrecognized line in grit status output")
    if not claims:
        raise ValueError("grit status output has no agent or claim lines")
    return claims


def claims_for_path(claims: list[dict[str, str]], path: str) -> list[dict[str, str]]:
    """Claims whose symbol id (``file::name``) belongs to this workspace-relative file."""
    target = Path(path).as_posix().lstrip("/")
    result = []
    for claim in claims:
        symbol_file = claim.get("symbol", "").split("::", 1)[0]
        if symbol_file == target:
            result.append(claim)
    return result


def advisory_text(claims: list[dict[str, str]]) -> str | None:
    """One advisory sentence for an approval card; None when nothing is claimed."""
    if not claims:
        return None
    parts = []
    for claim in claims:
        mode = " read" if claim.get("mode") == "read" else ""
        parts.append(f"{claim['symbol'].split('::')[-1]}{mode} held by "
                     f"{claim['agent']} ({claim['intent']})")
    return ("Peer claims (grit, advisory only): " + "; ".join(parts)
            + ". Coordination data from rtk-ai/grit.")


async def read_peer_claims(root: Path, info: dict[str, Any],
                           timeout_s: float = STATUS_TIMEOUT_S) -> dict[str, Any]:
    """Run the pinned ``grit status`` in the sandbox and parse its claim registry."""
    root = root.resolve(strict=True)
    command = _sandbox_command(root, info)
    process = await asyncio.create_subprocess_exec(
        *command, cwd="/", stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        limit=MAX_STATUS_BYTES + 8192)
    try:
        raw, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        await _kill(process)
        raise
    finally:
        if process.returncode is None:
            await _kill(process)
    if len(raw) > MAX_STATUS_BYTES:
        raise ValueError("grit status output exceeds its limit")
    if process.returncode != 0:
        # A failed exit never surfaces as "no claims": the caller reports
        # the advisory as unavailable instead.
        raise RuntimeError(f"grit status exited with {process.returncode}")
    text = raw.decode("utf-8", errors="strict")
    claims = parse_status(text)
    return {"claims": claims, "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "grit_executable": info["executable"], "grit_sha256": info["sha256"]}


async def _kill(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, 9)
    except (ProcessLookupError, PermissionError, AttributeError):
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


__all__ = ["GRIT_ID", "GRIT_LABEL", "advisory_text", "claims_for_path",
           "discover_grit", "has_grit_registry", "parse_status", "read_peer_claims"]
