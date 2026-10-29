"""Bubblewrap backend; keeps the existing Linux sandbox contract."""
import asyncio
import os
import signal


import ctypes.util
import shutil
import stat
from pathlib import Path
try:
    import resource
except ModuleNotFoundError:
    resource = None

from isycode.action_runtime import COMMAND_MAX_TIMEOUT_S, COMMAND_SYSTEM_BIN_DIRS, command_relative_path_valid, sandbox_program_valid
from isycode.lsp import network_deny_bootstrap
DEFAULT_TIMEOUT_S = 120

MAX_PROCESSES = 256
PYTHON = "/usr/bin/python3"
# Only the files dynamic linking and user lookups need; no hosts, resolv or keys.
ETC_FILES = ("ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives", "passwd", "group",
             "nsswitch.conf", "localtime")

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
    from isycode.command_runner import _no_symlinks
    relative = name.removeprefix("./")
    if (not command_relative_path_valid(relative) or not _no_symlinks(root, relative)
            or not _is_executable_file(root / relative)):
        raise ValueError("workspace program must be an executable, non-sensitive file without symlinks")
    return "/workspace/" + relative



def sandbox_command(sandbox: str, root: Path, program: str, argv: tuple[str, ...], cwd: str,
                    masks: tuple[tuple[str, bool], ...], *,
                    timeout_s: int = DEFAULT_TIMEOUT_S) -> list[str]:
    """Bubblewrap argv: system files read-only, only the workspace writable, sensitive paths masked."""
    args = [sandbox, "--die-with-parent", "--new-session", "--unshare-all",
            "--cap-drop", "ALL", "--clearenv", "--ro-bind", "/usr", "/usr"]
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
                 "--", PYTHON, "-I", "-c", command_bootstrap(timeout_s), program, *argv[1:]])
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
    # Bubblewrap only drops capabilities by itself when it does not run as root.
    # Refuse to exec the program if any effective capability survived.
    capability_check = (
        "try:\n"
        "    status = open('/proc/self/status', encoding='ascii').read().splitlines()\n"
        "    cap_eff = next(line for line in status if line.startswith('CapEff:'))\n"
        "    if int(cap_eff.split()[1], 16):\n"
        "        raise SystemExit('sandbox capability check failed')\n"
        "except (OSError, StopIteration, ValueError):\n"
        "    raise SystemExit('sandbox capability check failed')\n")
    return limits + capability_check + network_deny_bootstrap(MAX_PROCESSES)


class PosixSandbox:
    def relative_path_valid(self, value):
        return True  # Shared POSIX-relative validation already checked syntax.

    def unavailable_reason(self):
        return 'the command sandbox needs bubblewrap, libseccomp and python3 on Linux; commands stay disabled and there is no unsandboxed fallback'

    def executable(self):
        return sandbox_executable()

    def identity(self):
        return None  # Existing request already binds the exact Bubblewrap path.

    def resolve_program(self, root, name):
        return resolve_program(root, name)

    def program_valid(self, program, argv0):
        from isycode.action_runtime import sandbox_program_valid
        return sandbox_program_valid(program, argv0)

    async def start(self, staging, program, argv, cwd, masks, timeout_s, *, executable=None,
                    identity=None):
        command = sandbox_command(executable or self.executable(), staging, program,
                                  argv, cwd, masks, timeout_s=timeout_s)
        # bwrap is PID 1 in the sandbox: its own environment must carry nothing
        # from the host, or /proc/1/environ would leak it to the child.
        return await asyncio.create_subprocess_exec(*command, cwd='/', env={},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True)

    def terminate(self, process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

    async def finish(self, process):
        self.terminate(process)
        await process.wait()

    async def close(self, process):
        await self.finish(process)
