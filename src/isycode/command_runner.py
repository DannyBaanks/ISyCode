"""Run one reviewed command inside the workspace sandbox after Authority and IsySentinel.

The argv is never given to a shell. Bubblewrap exposes read-only system files
and a private copy of the workspace; every sensitive path the chat tools refuse
(``.git``, ``.env``, keys…) is masked, the ``.isyroot`` marker is read-only,
and a seccomp bootstrap denies socket syscalls before the program starts.
The user tree is unchanged until that measured diff is promoted. There is no
host-shell fallback. Each run needs a ``workspace.command.run`` grant for the
exact sandbox executable plus a fresh approval bound to the reviewed request.
"""
from __future__ import annotations

import asyncio
import ctypes.util
import hashlib
import json
import os
import secrets
import shutil
import signal
import stat
from dataclasses import dataclass
from pathlib import Path

try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - no resource limits outside POSIX
    resource = None

from isycode.action_runtime import (
    COMMAND_MAX_OUTPUT_BYTES, COMMAND_MAX_TIMEOUT_S, COMMAND_SYSTEM_BIN_DIRS, ActionOutcome,
    ActionReceipt, ProductActionGate, WorkspaceReadSystembility, command_argv_valid,
    command_relative_path_valid, sandbox_program_valid,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.lsp import network_deny_bootstrap
from isycode.security import ActionRequest
from isycode.staging import (
    StagingError, cleanup_staging, measure_changes, prepare_staging, promote_changes,
)
from isycode.workspace_authority import WorkspaceAuthority

OWNER_ID = "workspace_command"
COMMAND_TOOL_NAME = "workspace_run"
DEFAULT_TIMEOUT_S = 120
MAX_PROCESSES = 256
PYTHON = "/usr/bin/python3"
# Only the files dynamic linking and user lookups need; no hosts, resolv or keys.
ETC_FILES = ("ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives", "passwd", "group",
             "nsswitch.conf", "localtime")

COMMAND_TOOL = {"type": "function", "function": {
    "name": COMMAND_TOOL_NAME,
    "description": (
        "Run one program (for example tests, a build or a linter) in a sandbox of this workspace. "
        "The user reviews the exact command and must approve every run. There is no shell: pass "
        "the program and its arguments as a list, without pipes, redirects or variables. The "
        "network is blocked and sensitive files are hidden. Commands may change workspace files "
        "and those changes cannot be undone with /undo."),
    "parameters": {"type": "object", "properties": {
        "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                 "description": "Program and arguments, e.g. [\"python3\", \"-m\", \"pytest\", \"-q\"]."},
        "cwd": {"type": "string", "description": "Workspace-relative folder; defaults to the root."},
        "timeout_s": {"type": "integer", "minimum": 1, "maximum": COMMAND_MAX_TIMEOUT_S,
                      "description": f"Seconds before the command is stopped; default {DEFAULT_TIMEOUT_S}."},
    }, "required": ["argv"], "additionalProperties": False},
}}


def sandbox_executable() -> str | None:
    """The resolved bubblewrap path when every sandbox ingredient is present."""
    if os.name != "posix" or resource is None or not hasattr(resource, "setrlimit"):
        return None
    found = shutil.which("bwrap")
    if not found or not ctypes.util.find_library("seccomp") or not os.access(PYTHON, os.X_OK):
        return None
    try:
        return str(Path(found).resolve(strict=True))
    except (OSError, RuntimeError):
        return None


def _is_executable_file(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and os.access(path, os.X_OK)


def _no_symlinks(root: Path, relative: str) -> bool:
    current = root
    for part in relative.split("/"):
        current = current / part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                return False
        except OSError:
            return False
    return True


def resolve_program(root: Path, name: str) -> str:
    """Map argv[0] to the path it has inside the sandbox; nothing is searched in the workspace."""
    if "/" not in name:
        for folder in COMMAND_SYSTEM_BIN_DIRS:
            if _is_executable_file(Path(folder) / name):
                return f"{folder}/{name}"
        raise ValueError(f"program {name!r} is not installed in {', '.join(COMMAND_SYSTEM_BIN_DIRS)}")
    if name.startswith("/"):
        if sandbox_program_valid(name, name) and _is_executable_file(Path(name)):
            return name
        raise ValueError("absolute programs must come from a system bin folder")
    relative = name.removeprefix("./")
    if (not command_relative_path_valid(relative) or not _no_symlinks(root, relative)
            or not _is_executable_file(root / relative)):
        raise ValueError("workspace program must be an executable, non-sensitive file without symlinks")
    return "/workspace/" + relative


def sensitive_entries(root: Path) -> tuple[tuple[str, bool], ...]:
    """Every sensitive file or folder in the workspace, as (relative path, is_folder).

    Symlinks are not masked: only the workspace is mounted, so their targets
    are either outside the sandbox or a real entry that is masked itself. The
    scan is exhaustive: command execution never proceeds with only a partial
    list of sensitive paths, and large workspaces are not rejected by an
    arbitrary entry-count ceiling.
    """
    found: list[tuple[str, bool]] = []
    stack = [root]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                is_folder = entry.is_dir(follow_symlinks=False)
                if WorkspaceReadSystembility.is_sensitive_name(entry.name):
                    found.append((Path(entry.path).relative_to(root).as_posix(), is_folder))
                elif is_folder:
                    stack.append(Path(entry.path))
    return tuple(sorted(found))


def masked_digest(masks: tuple[tuple[str, bool], ...]) -> str:
    return hashlib.sha256(json.dumps(masks, separators=(",", ":")).encode("utf-8")).hexdigest()


def sandbox_command(sandbox: str, root: Path, program: str, argv: tuple[str, ...], cwd: str,
                    masks: tuple[tuple[str, bool], ...], *,
                    timeout_s: int = DEFAULT_TIMEOUT_S) -> list[str]:
    """Bubblewrap argv: system files read-only, only the workspace writable, sensitive paths masked."""
    args = [sandbox, "--die-with-parent", "--new-session", "--unshare-all", "--share-net",
            "--clearenv", "--ro-bind", "/usr", "/usr"]
    for source, destination, alias in (("/bin", "/bin", "/usr/bin"), ("/sbin", "/sbin", "/usr/sbin"),
                                       ("/lib", "/lib", "/usr/lib"),
                                       ("/lib64", "/lib64", "/usr/lib64")):
        if Path(source).is_symlink():
            args.extend(["--symlink", alias, destination])
        elif Path(source).exists():
            args.extend(["--ro-bind", source, destination])
    for name in ETC_FILES:
        if Path("/etc", name).exists():
            args.extend(["--ro-bind", f"/etc/{name}", f"/etc/{name}"])
    args.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--dir", "/workspace", "--bind", str(root), "/workspace"])
    # The workspace identity marker stays exactly as it is.
    if (root / ".isyroot").is_file() and not (root / ".isyroot").is_symlink():
        args.extend(["--ro-bind", str(root / ".isyroot"), "/workspace/.isyroot"])
    for relative, is_folder in masks:
        if is_folder:
            args.extend(["--tmpfs", f"/workspace/{relative}"])
        else:
            args.extend(["--ro-bind", "/dev/null", f"/workspace/{relative}"])
    args.extend(["--chdir", "/workspace" if cwd == "." else f"/workspace/{cwd}",
                 "--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp",
                 "--setenv", "PATH", ":".join(COMMAND_SYSTEM_BIN_DIRS),
                 "--setenv", "LANG", "C.UTF-8", "--setenv", "TERM", "dumb",
                 "--setenv", "NO_COLOR", "1",
                 "--", PYTHON, "-c", command_bootstrap(timeout_s), program, *argv[1:]])
    return args


def command_bootstrap(timeout_s: int) -> str:
    """Install hard resource limits in the child before any user program runs.

    Setting limits from the parent races both program execution and reaping:
    a fast command can exit while the busy UI is waiting to resume.
    """
    if type(timeout_s) is not int or not 1 <= timeout_s <= COMMAND_MAX_TIMEOUT_S:
        raise ValueError("command timeout is invalid")
    cpu = timeout_s + 10
    limits = ("import resource\n"
              f"resource.setrlimit(resource.RLIMIT_CPU, ({cpu}, {cpu}))\n"
              "resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))\n"
              f"resource.setrlimit(resource.RLIMIT_FSIZE, ({512 * 1024**2}, {512 * 1024**2}))\n")
    return limits + network_deny_bootstrap(MAX_PROCESSES)


@dataclass(frozen=True)
class CommandPreview:
    request: ActionRequest
    argv: tuple[str, ...]
    program: str
    cwd: str
    timeout_s: int
    masks: tuple[tuple[str, bool], ...]


class CommandRunOwner:
    """The only execution owner for ``workspace.command.run``."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id=OWNER_ID)

    def prepare(self, argv: object, cwd: object = ".",
                timeout_s: object = DEFAULT_TIMEOUT_S) -> CommandPreview:
        """Build the exact request the user reviews. Raises ValueError when it cannot run."""
        if isinstance(argv, list):
            argv = tuple(argv)
        if not command_argv_valid(argv):
            raise ValueError("argv must be 1–64 non-empty strings without NUL characters")
        cwd = "." if cwd in (None, "", "./") else cwd
        if isinstance(cwd, str):
            cwd = cwd.removeprefix("./").rstrip("/") or "."
        if not command_relative_path_valid(cwd, allow_root=True):
            raise ValueError("cwd must be a non-sensitive folder inside the workspace")
        if cwd != "." and (not _no_symlinks(self.root, cwd) or not (self.root / cwd).is_dir()):
            raise ValueError("cwd must be an existing folder without symlinks")
        if type(timeout_s) is not int or not 1 <= timeout_s <= COMMAND_MAX_TIMEOUT_S:
            raise ValueError(f"timeout must be 1–{COMMAND_MAX_TIMEOUT_S} seconds")
        sandbox = sandbox_executable()
        if sandbox is None:
            raise ValueError("the command sandbox needs bubblewrap, libseccomp and python3 on Linux")
        program = resolve_program(self.root, argv[0])
        masks = sensitive_entries(self.root)
        request = ActionRequest(
            "workspace.command.run", self.root, program,
            {"argv": argv, "program": program, "cwd": cwd, "timeout_s": timeout_s,
             "network": "denied", "executable": sandbox, "workspace_root": str(self.root),
             "masked_sha256": masked_digest(masks), "masked_count": len(masks),
             "max_output_bytes": COMMAND_MAX_OUTPUT_BYTES},
            execution_owner="workspace_command")
        return CommandPreview(request, argv, program, cwd, timeout_s, masks)

    async def run(self, preview: CommandPreview,
                  approval: ActionApproval | None) -> ActionOutcome:
        """Run in staging and promote the measured diff after the process exits."""
        return await self._run(preview, approval, promote=True)

    async def run_staged(self, preview: CommandPreview,
                         approval: ActionApproval | None) -> ActionOutcome:
        """Run in staging and leave the user tree untouched."""
        return await self._run(preview, approval, promote=False)

    async def _run(self, preview: CommandPreview, approval: ActionApproval | None, *,
                   promote: bool) -> ActionOutcome:
        request = preview.request
        # Re-derive the sandbox facts: a new secret or a swapped program after
        # review denies instead of running with a stale mask set.
        try:
            masks = sensitive_entries(self.root)
            program = resolve_program(self.root, preview.argv[0])
        except (OSError, ValueError) as exc:
            return ActionOutcome("Command denied.", "DENY", None, str(exc)[:200] or "sandbox facts unavailable")
        if (masks != preview.masks or masked_digest(masks) != request.parameters["masked_sha256"]
                or program != preview.program or sandbox_executable() != request.parameters["executable"]):
            return ActionOutcome("Command denied.", "DENY", None,
                                 "sensitive files or the program changed after review")
        _, decision = self.gate.authorize(request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = "; ".join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome("Command denied.", "DENY", None, reason)
        try:
            result = await self._execute(preview, promote=promote)
        except (OSError, RuntimeError, ValueError) as exc:
            detail = str(exc).strip() or type(exc).__name__
            return ActionOutcome("Command could not start.", "ERROR", None,
                                 f"sandboxed command failed to start ({detail[:200]})")
        result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "workspace.command.run", request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result_text.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result_text):
            return ActionOutcome("Command receipt failed verification.", "NOT_VERIFIABLE", None,
                                 "local request/result digest did not match")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Command receipt could not be persisted.", "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(result_text, "ALLOW", receipt,
                             f"sandboxed command finished with exit code {result['exit_code']}")

    async def _execute(self, preview: CommandPreview, *, promote: bool) -> dict:
        params = preview.request.parameters
        try:
            staging = prepare_staging(self.root)
        except StagingError as exc:
            raise OSError(str(exc)) from exc
        try:
            command = sandbox_command(params["executable"], staging.root, preview.program,
                                      preview.argv, preview.cwd, preview.masks,
                                      timeout_s=preview.timeout_s)
            proc = await asyncio.create_subprocess_exec(
                *command, cwd="/", stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                start_new_session=True)
            output = bytearray()
            total = 0
            timed_out = False

            async def drain() -> None:
                nonlocal total
                while chunk := await proc.stdout.read(8192):
                    total += len(chunk)
                    room = COMMAND_MAX_OUTPUT_BYTES - len(output)
                    if room > 0:
                        output.extend(chunk[:room])
                await proc.wait()

            try:
                await asyncio.wait_for(drain(), timeout=preview.timeout_s)
            except asyncio.TimeoutError:
                timed_out = True
                self._kill(proc)
                await proc.wait()
            except asyncio.CancelledError:
                self._kill(proc)
                await proc.wait()
                raise
            changes = measure_changes(staging)
            if promote:
                applied, refused = promote_changes(staging, changes)
                pending: list[str] = []
            else:
                applied, refused = [], []
                pending = [item["path"] for item in changes]
            return {"argv": list(preview.argv), "cwd": preview.cwd,
                    "exit_code": proc.returncode, "timed_out": timed_out,
                    "output": output.decode("utf-8", errors="replace"),
                    "output_truncated": total > len(output), "output_bytes": total,
                    "staging": {
                        "backend": "copy",
                        "promoted_count": len(applied),
                        "promoted": applied[:300],
                        "pending_count": len(pending),
                        "pending": pending[:300],
                        "refused_count": len(refused),
                        "refused": refused[:300],
                    }}
        finally:
            cleanup_staging(staging)

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass


__all__ = [
    "COMMAND_TOOL", "COMMAND_TOOL_NAME", "CommandPreview", "CommandRunOwner", "DEFAULT_TIMEOUT_S",
    "masked_digest", "resolve_program", "sandbox_command", "sandbox_executable",
    "sensitive_entries",
]
