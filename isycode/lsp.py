"""Read-only LSP adapter for installed servers with syscall-level network denial."""
from __future__ import annotations

import asyncio
import ctypes.util
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any

try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - no resource limits outside POSIX
    resource = None

MAX_FRAME_BYTES = 2_000_000
MAX_SYMBOLS = 500
MAX_INDEXED_SOURCE_BYTES = 64 * 1024


def _read_indexed_source(root: Path, path: Path) -> str | None:
    """Read one bounded regular workspace source without following links or blocking."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    directory_fd = file_fd = None
    try:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_fd = os.open(root, directory_flags)
        for component in relative.parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(relative.parts[-1], file_flags, dir_fd=directory_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_INDEXED_SOURCE_BYTES:
            return None
        chunks = bytearray()
        while len(chunks) <= MAX_INDEXED_SOURCE_BYTES:
            chunk = os.read(file_fd, min(8192, MAX_INDEXED_SOURCE_BYTES + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) > MAX_INDEXED_SOURCE_BYTES:
            return None
        return chunks.decode("utf-8")
    except (OSError, UnicodeError):
        return None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)

# This host denies creating a network namespace, and Bubblewrap's --seccomp FD
# path cannot install a filter through the outer container's prctl policy.
# Load libseccomp through its seccomp(2) API in a tiny trusted bootstrap after
# Bubblewrap has finished constructing namespaces/mounts and before exec'ing
# the language server. The filter is inherited across exec and child processes.
_SECCOMP_BOOTSTRAP_TEMPLATE = r'''import ctypes, os, resource, sys
# Apply process-count limits only after Bubblewrap has created its namespaces.
# Applying RLIMIT_NPROC to the launcher can make namespace setup fail with
# EAGAIN when the host user already owns more than this many processes.
resource.setrlimit(resource.RLIMIT_NPROC, (@NPROC@, @NPROC@))
lib = ctypes.CDLL("libseccomp.so.2")
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_rule_add.restype = ctypes.c_int
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_load.restype = ctypes.c_int
lib.seccomp_release.argtypes = [ctypes.c_void_p]
ctx = lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
if not ctx:
    raise SystemExit("seccomp policy unavailable")
try:
    denied = ("socket socketpair connect bind listen accept accept4 sendto recvfrom "
                "sendmsg recvmsg sendmmsg recvmmsg shutdown setsockopt getsockopt "
              "getsockname getpeername io_uring_setup io_uring_enter io_uring_register "
              "socketcall unshare setns").split()
    if @LOCAL_IPC@:
        # TypeScript's child uses an anonymous AF_UNIX pair, never a named socket.
        # Deny every other socketpair domain and keep socket/connect/bind denied.
        class ArgCmp(ctypes.Structure):
            _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_int),
                        ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]
        lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                               ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ArgCmp)]
        lib.seccomp_rule_add_array.restype = ctypes.c_int
        number = lib.seccomp_syscall_resolve_name(b"socketpair")
        comparison = ArgCmp(0, 1, 1, 0)  # argument 0 != AF_UNIX (SCMP_CMP_NE)
        if number < 0 or lib.seccomp_rule_add_array(ctx, 0x00050000 | 1, number, 1, ctypes.byref(comparison)):
            raise SystemExit("could not compile local IPC policy")
        denied.remove("socketpair")
        # libuv receives IPC frames through recvmsg. No network/named socket can
        # be created or inherited: stdio is pipe-only and all other FDs closed.
        denied.remove("sendmsg")
        denied.remove("recvmsg")
    for name in denied:
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number >= 0 and lib.seccomp_rule_add(ctx, 0x00050000 | 1, number, 0):
            raise SystemExit("could not compile network-deny policy")
    if lib.seccomp_load(ctx):
        raise SystemExit("could not install network-deny policy")
finally:
    lib.seccomp_release(ctx)
os.execv(sys.argv[1], sys.argv[1:])
'''


def network_deny_bootstrap(max_processes: int = 32, *, allow_local_ipc: bool = False) -> str:
    """Python bootstrap that caps processes, denies sockets, then execs argv[1:]."""
    if type(max_processes) is not int or not 1 <= max_processes <= 4096:
        raise ValueError("process limit is invalid")
    if type(allow_local_ipc) is not bool:
        raise ValueError("Invalid local IPC policy")
    return _SECCOMP_BOOTSTRAP_TEMPLATE.replace("@NPROC@", str(max_processes)).replace("@LOCAL_IPC@", repr(allow_local_ipc))


_SECCOMP_BOOTSTRAP = network_deny_bootstrap(32)


def discover_servers() -> list[dict[str, Any]]:
    """Inspect known LSP executables without starting them."""
    found: list[dict[str, Any]] = []
    bwrap = shutil.which("bwrap")
    node = shutil.which("node")
    pyright = shutil.which("pyright-langserver")
    if pyright:
        script = Path(pyright).resolve(strict=True)
        node_path = Path(node).resolve(strict=True) if node else None
        sandbox = Path(bwrap).resolve(strict=True) if bwrap else None
        package_root = script.parent
        ready = bool(node_path and sandbox and ctypes.util.find_library("seccomp")
                     and resource is not None
                     and hasattr(resource, "prlimit") and script.is_file()
                     and (package_root / "dist" / "pyright-langserver.js").is_file())
        found.append({
            "id": "pyright",
            "label": "Pyright Language Server",
            "state": "sandbox_ready" if ready else "installed_unavailable",
            "command": pyright,
            "server_executable": str(script),
            "node_executable": str(node_path) if node_path else "",
            "sandbox_executable": str(sandbox) if sandbox else "",
            "capability": "workspace/symbol",
        })
    for server_id, label, command in (
        ("rust-analyzer", "rust-analyzer", "rust-analyzer"),
        ("typescript", "TypeScript Language Server", "typescript-language-server"),
        ("gopls", "gopls", "gopls"),
        ("clangd", "clangd", "clangd"),
        ("jdtls", "Eclipse JDT Language Server", "jdtls"),
        ("pylsp", "Python LSP Server", "pylsp"),
    ):
        executable = shutil.which(command)
        if not executable:
            continue
        script = Path(executable).resolve(strict=True)
        # rustup shims dispatch by argv[0]; execute the actual component instead.
        if server_id == "rust-analyzer" and script.name == "rustup":
            toolchains = Path(os.environ.get("RUSTUP_HOME", Path.home() / ".rustup")) / "toolchains"
            candidates = sorted(toolchains.glob("*/bin/rust-analyzer"))
            candidates.sort(key=lambda value: not value.parts[-3].startswith("stable"))
            script = next((value.resolve() for value in candidates if value.is_file()), script)
        supported = server_id in {"rust-analyzer", "gopls", "clangd", "typescript"}
        runtime_ready = script.is_file() and os.access(script, os.X_OK) and script.name != "rustup"
        node_path = Path(node).resolve() if node and server_id == "typescript" else None
        if server_id == "typescript":
            packages = next((parent for parent in script.parents if parent.name == "node_modules"), None)
            runtime_ready = bool(node_path and packages and (packages / "typescript/lib/tsserver.js").is_file())
        ready = bool(supported and runtime_ready and bwrap and ctypes.util.find_library("seccomp")
                     and resource is not None and hasattr(resource, "prlimit"))
        go = shutil.which("go") if server_id == "gopls" else None
        runtime = str(Path(go).resolve(strict=True)) if go else ""
        found.append({"id": server_id, "label": label,
                      "state": "sandbox_ready" if ready else "installed_unavailable" if supported else "installed_unsupported",
                      "command": executable, "server_executable": str(script),
                      "runtime_executable": runtime,
                      "node_executable": str(node_path) if node_path else "",
                      "sandbox_executable": str(Path(bwrap).resolve()) if bwrap else "",
                      "capability": "workspace/symbol" if ready else ""})
    return found


def _frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError("LSP request exceeds the frame limit")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload


async def _read_message(reader: asyncio.StreamReader) -> dict[str, Any]:
    content_length: int | None = None
    header_size = 0
    while True:
        line = await reader.readline()
        header_size += len(line)
        if not line or header_size > 8192:
            raise RuntimeError("LSP server returned invalid headers")
        if line in {b"\r\n", b"\n"}:
            break
        key, sep, value = line.partition(b":")
        if sep and key.strip().lower() == b"content-length":
            try:
                content_length = int(value.strip())
            except ValueError as exc:
                raise RuntimeError("LSP server returned an invalid frame length") from exc
    if content_length is None or not 0 <= content_length <= MAX_FRAME_BYTES:
        raise RuntimeError("LSP server frame is missing or exceeds 2 MB")
    payload = await reader.readexactly(content_length)
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise RuntimeError("LSP server returned a non-object message")
    return message


def _server_request_response(message: dict[str, Any]) -> dict[str, Any] | None:
    """Answer the small, read-only set of client requests Pyright may send.

    Requests that would mutate the editor/workspace are explicitly rejected.
    A ``None`` return means the message was a notification and needs no reply.
    """
    if "method" not in message or "id" not in message:
        return None
    method = message.get("method")
    request_id = message.get("id")
    if method == "workspace/configuration":
        params = message.get("params")
        items = params.get("items", []) if isinstance(params, dict) else []
        result: Any = [None for _ in items] if isinstance(items, list) else []
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if method in {"window/workDoneProgress/create", "client/registerCapability",
                  "client/unregisterCapability", "window/showMessageRequest"}:
        return {"jsonrpc": "2.0", "id": request_id, "result": None}
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": "Client request is not supported"}}


async def _response(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                    request_id: int, timeout_s: float,
                    expected: type = dict) -> dict[str, Any]:
    async def receive() -> dict[str, Any]:
        while True:
            message = await _read_message(reader)
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError("LSP server rejected the request")
                result = message.get("result")
                if not isinstance(result, expected):
                    raise RuntimeError("LSP server returned an invalid result")
                return {"result": result}
            response = _server_request_response(message)
            if response is not None:
                writer.write(_frame(response))
                await writer.drain()
    return await asyncio.wait_for(receive(), timeout=timeout_s)


def _sandbox_command(root: Path, server: dict[str, Any]) -> list[str]:
    sandbox = str(Path(server["sandbox_executable"]).resolve(strict=True))
    script = Path(server["server_executable"]).resolve(strict=True)
    node = Path(server["node_executable"]).resolve(strict=True) if server["node_executable"] else None
    if not script.is_file() or (node is not None and (not node.is_file() or not os.access(node, os.X_OK))):
        raise RuntimeError("Language server runtime files are unavailable")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError("Workspace root is unavailable")
    # Only the selected workspace and read-only OS/runtime files are visible.
    # This host denies a network namespace. Keep the network namespace shared,
    # then install a fail-closed seccomp deny-list before the untrusted server
    # starts. No home directory or credentials are mounted.
    args = [sandbox, "--die-with-parent", "--unshare-all", "--share-net", "--clearenv",
            "--ro-bind", "/usr", "/usr"]
    for source, destination, alias in (("/bin", "/bin", "/usr/bin"),
                                       ("/lib", "/lib", "/usr/lib"),
                                       ("/lib64", "/lib64", "/usr/lib64")):
        if Path(source).is_symlink():
            args.extend(["--symlink", alias, destination])
        elif Path(source).exists():
            args.extend(["--ro-bind", source, destination])
    runtime_path = "/usr/bin:/bin:/runtime"
    args.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--dir", "/runtime", "--dir", "/workspace"])
    if server["id"] == "pyright":
        args.extend(["--dir", "/runtime/pyright", "--ro-bind", str(script.parent), "/runtime/pyright",
                     "--ro-bind", str(node), "/runtime/node"])
        invocation = ["/runtime/node", "/runtime/pyright/langserver.index.js", "--stdio"]
    elif server["id"] == "typescript":
        packages = next(parent for parent in script.parents if parent.name == "node_modules")
        args.extend(["--dir", "/runtime/packages", "--ro-bind", str(packages), "/runtime/packages",
                     "--ro-bind", str(node), "/runtime/node"])
        invocation = ["/runtime/node", "/runtime/packages/" + script.relative_to(packages).as_posix(), "--stdio"]
    elif server["id"] in {"rust-analyzer", "gopls", "clangd"}:
        args.extend(["--ro-bind", str(script), "/runtime/server"])
        invocation = ["/runtime/server"]
        if server["id"] == "clangd":
            invocation += ["--background-index=false", "--clang-tidy=false", "--enable-config=false"]
        if server["id"] == "rust-analyzer" and (script.parent.parent / "lib/rustlib").is_dir():
            args.extend(["--dir", "/runtime/toolchain", "--ro-bind", str(script.parent.parent), "/runtime/toolchain",
                         "--setenv", "RUST_SYSROOT", "/runtime/toolchain",
                         "--setenv", "CARGO_NET_OFFLINE", "true",
                         "--setenv", "RUSTC", "/runtime/toolchain/bin/rustc",
                         "--setenv", "CARGO", "/runtime/toolchain/bin/cargo"])
            runtime_path += ":/runtime/toolchain/bin"
        if server["id"] == "gopls":
            go = server.get("runtime_executable")
            if go:
                go_root = Path(go).resolve(strict=True).parent.parent
                if (go_root / "src").is_dir() and (go_root / "pkg").is_dir():
                    args.extend(["--dir", "/runtime/go", "--ro-bind", str(go_root), "/runtime/go",
                                 "--setenv", "GOROOT", "/runtime/go", "--setenv", "GOPROXY", "off",
                                 "--setenv", "GOSUMDB", "off", "--setenv", "GOTOOLCHAIN", "local"])
                    runtime_path += ":/runtime/go/bin"
    else:
        raise RuntimeError("Unsupported LSP runtime")
    args.extend(["--ro-bind", str(root), "/workspace", "--chdir", "/workspace",
                 "--setenv", "HOME", "/tmp", "--setenv", "XDG_CONFIG_HOME", "/tmp/config",
                 "--setenv", "PATH", runtime_path,
                 "--setenv", "RAYON_NUM_THREADS", "2", "--setenv", "GOMAXPROCS", "2",
                 "--", "/usr/bin/python3", "-c", network_deny_bootstrap(32, allow_local_ipc=server["id"] == "typescript"), *invocation])
    return args


async def workspace_symbols(root: Path, query: str,
                                    server: dict[str, Any],
                                    timeout_s: float = 25.0) -> dict[str, Any]:
    """Perform initialize + workspace/symbol in a bubblewrap, read-only sandbox."""
    if not isinstance(query, str) or not query.strip() or len(query) > 256:
        raise ValueError("Symbol query must contain 1–256 characters")
    root = root.resolve(strict=True)
    command = _sandbox_command(root, server)
    proc = await asyncio.create_subprocess_exec(
        *command, cwd="/", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        limit=MAX_FRAME_BYTES + 8192,
    )
    deadline = asyncio.get_running_loop().time() + timeout_s
    try:
        if resource is None:
            raise RuntimeError("OS process limits are unavailable")
        resource.prlimit(proc.pid, resource.RLIMIT_CPU, (30, 30))
        resource.prlimit(proc.pid, resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.prlimit(proc.pid, resource.RLIMIT_NOFILE, (128, 128))
        resource.prlimit(proc.pid, resource.RLIMIT_FSIZE, (4 * 1024**2, 4 * 1024**2))
    except (AttributeError, OSError, ValueError) as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("LSP process resource limits could not be applied") from exc
    try:
        initialize = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "processId": None,
                "rootUri": "file:///workspace",
                "workspaceFolders": [{"uri": "file:///workspace", "name": root.name}],
                "capabilities": {}, "trace": "off",
                "initializationOptions": ({"cargo": {"buildScripts": {"enable": False}},
                    "procMacro": {"enable": False}, "checkOnSave": False,
                    "check": {"enable": False}} if server["id"] == "rust-analyzer" else
                    {"tsserver": {"path": "/runtime/packages/typescript/lib/tsserver.js",
                                  "maxTsServerMemory": 256, "useSyntaxServer": "never"}}
                    if server["id"] == "typescript" else {}),
                "clientInfo": {"name": "isycode", "version": "0.1.0"},
            },
        }
        proc.stdin.write(_frame(initialize))
        await proc.stdin.drain()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError("Language server initialize exceeded its deadline")
        initialized = await _response(proc.stdout, proc.stdin, 1, remaining)
        capabilities = initialized["result"].get("capabilities", {})
        if not isinstance(capabilities, dict) or not capabilities.get("workspaceSymbolProvider"):
            raise RuntimeError("Language server did not advertise workspace symbol search")
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        # Open a bounded set of ordinary source files so document-indexed servers
        # (clangd and TypeScript) can answer workspace/symbol without background writes.
        if server["id"] != "pyright":
            from isycode.action_runtime import WorkspaceReadSystembility
            extensions = {"rust-analyzer": {".rs": "rust"}, "typescript": {".ts": "typescript", ".tsx": "typescriptreact", ".js": "javascript"},
                          "gopls": {".go": "go"}, "clangd": {".c": "c", ".cpp": "cpp", ".h": "c"}}[server["id"]]
            opened = total = visited = 0
            for directory, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = sorted(name for name in dirs if not name.startswith(".")
                    and name not in {"node_modules", "target", "build", "dist", "vendor", "venv"}
                    and not (Path(directory) / name).is_symlink()
                    and not WorkspaceReadSystembility.is_sensitive_name(name))
                for name in sorted(files):
                    visited += 1
                    path = Path(directory) / name
                    if (path.suffix not in extensions or path.is_symlink() or name.startswith(".")
                            or WorkspaceReadSystembility.is_sensitive_name(name)):
                        continue
                    try:
                        text = _read_indexed_source(root, path)
                    except (OSError, UnicodeError):
                        continue
                    if text is None:
                        continue
                    if total + len(text.encode("utf-8")) > 512 * 1024:
                        break
                    relative = path.relative_to(root)
                    from urllib.parse import quote
                    proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
                        "textDocument": {"uri": "file:///workspace/" + quote(relative.as_posix()),
                                         "languageId": extensions[path.suffix], "version": 1, "text": text}}}))
                    opened += 1; total += len(text.encode("utf-8"))
                    if opened >= 50:
                        break
                if opened >= 50 or visited >= 5000 or total >= 512 * 1024:
                    break
            await proc.stdin.drain()
        symbols: list[Any] = []
        request_id = 1
        for delay in (0.0, 0.2, 0.5, 0.8):
            if delay:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError("Language server workspace indexing exceeded its deadline")
                await asyncio.sleep(min(delay, remaining))
            request_id += 1
            proc.stdin.write(_frame({"jsonrpc": "2.0", "id": request_id,
                                     "method": "workspace/symbol",
                                     "params": {"query": query.strip()}}))
            await proc.stdin.drain()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError("Language server workspace search exceeded its deadline")
            response = await _response(proc.stdout, proc.stdin, request_id, remaining, list)
            symbols = response["result"]
            if symbols:
                break
        if not isinstance(symbols, list):
            raise RuntimeError("Language server returned malformed workspace symbols")
        clipped = symbols[:MAX_SYMBOLS]
        clean = []
        for item in clipped:
            if not isinstance(item, dict):
                continue
            location = item.get("location", {})
            uri = location.get("uri", "") if isinstance(location, dict) else ""
            if uri and uri != "file:///workspace" and not uri.startswith("file:///workspace/"):
                continue
            clean.append(item)
        shutdown_id = request_id + 1
        proc.stdin.write(_frame({"jsonrpc": "2.0", "id": shutdown_id,
                                 "method": "shutdown", "params": None}))
        await proc.stdin.drain()
        try:
            await _response(proc.stdout, proc.stdin, shutdown_id, 2.0)
        except (asyncio.TimeoutError, RuntimeError):
            pass
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "exit", "params": None}))
        await proc.stdin.drain()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        return {
            "server": server["id"],
            "protocol": "LSP",
            "operation": "workspace/symbol",
            "query": query.strip(),
            "workspace_root": str(root),
            "symbols": clean,
            "truncated": len(symbols) > MAX_SYMBOLS,
            "sandbox": {"read_only_workspace": True,
                        "network": "network socket access denied by seccomp; anonymous local IPC allowed only for TypeScript"},
        }
    except (asyncio.CancelledError, Exception):
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise


async def pyright_workspace_symbols(root: Path, query: str, server: dict[str, Any],
                                    timeout_s: float = 25.0) -> dict[str, Any]:
    """Compatibility entrypoint for the owned multi-server symbols adapter."""
    return await workspace_symbols(root, query, server, timeout_s)


MAX_DIAGNOSTICS = 100
SEVERITIES = {1: "error", 2: "warning", 3: "information", 4: "hint"}


async def _diagnostics_session(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                               root_name: str, relative_path: str, text: str,
                               timeout_s: float) -> list[dict[str, Any]]:
    """initialize → didOpen → first publishDiagnostics for that file → shutdown."""
    uri = "file:///workspace/" + relative_path
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    def remaining() -> float:
        left = deadline - loop.time()
        if left <= 0:
            raise asyncio.TimeoutError("LSP diagnostics exceeded their deadline")
        return left

    writer.write(_frame({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"processId": None, "rootUri": "file:///workspace",
                   "workspaceFolders": [{"uri": "file:///workspace", "name": root_name}],
                   "capabilities": {"textDocument": {"publishDiagnostics": {}}},
                   "trace": "off", "clientInfo": {"name": "isycode", "version": "0.1.0"}}}))
    await writer.drain()
    await _response(reader, writer, 1, remaining())
    writer.write(_frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
    writer.write(_frame({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
        "textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": text}}}))
    await writer.drain()

    async def wait_for_diagnostics() -> list[Any]:
        while True:
            message = await _read_message(reader)
            params = message.get("params")
            if (message.get("method") == "textDocument/publishDiagnostics"
                    and isinstance(params, dict) and params.get("uri") == uri):
                diagnostics = params.get("diagnostics")
                return diagnostics if isinstance(diagnostics, list) else []
            response = _server_request_response(message)
            if response is not None:
                writer.write(_frame(response))
                await writer.drain()

    raw = await asyncio.wait_for(wait_for_diagnostics(), timeout=remaining())
    clean = []
    for item in raw[:MAX_DIAGNOSTICS]:
        if not isinstance(item, dict):
            continue
        start = (item.get("range") or {}).get("start") or {}
        clean.append({
            "line": int(start.get("line", 0)) + 1 if isinstance(start.get("line"), int) else 0,
            "column": int(start.get("character", 0)) + 1 if isinstance(start.get("character"), int) else 0,
            "severity": SEVERITIES.get(item.get("severity"), "error"),
            "message": str(item.get("message", ""))[:500],
            "rule": str(item.get("code", ""))[:80],
        })
    try:
        writer.write(_frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None}))
        await writer.drain()
        await _response(reader, writer, 2, min(2.0, max(0.1, deadline - loop.time())), type(None))
        writer.write(_frame({"jsonrpc": "2.0", "method": "exit", "params": None}))
        await writer.drain()
    except (asyncio.TimeoutError, RuntimeError, OSError):
        pass
    return clean


async def pyright_diagnostics(root: Path, relative_path: str, text: str,
                              server: dict[str, Any], timeout_s: float = 25.0) -> dict[str, Any]:
    """Language server diagnostics for one file, in the same read-only, network-denied sandbox."""
    root = root.resolve(strict=True)
    command = _sandbox_command(root, server)
    proc = await asyncio.create_subprocess_exec(
        *command, cwd="/", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        limit=MAX_FRAME_BYTES + 8192)
    try:
        if resource is None:
            raise RuntimeError("OS process limits are unavailable")
        resource.prlimit(proc.pid, resource.RLIMIT_CPU, (30, 30))
        resource.prlimit(proc.pid, resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.prlimit(proc.pid, resource.RLIMIT_NOFILE, (128, 128))
        resource.prlimit(proc.pid, resource.RLIMIT_FSIZE, (4 * 1024**2, 4 * 1024**2))
    except (AttributeError, OSError, ValueError) as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("LSP process resource limits could not be applied") from exc
    try:
        diagnostics = await _diagnostics_session(proc.stdout, proc.stdin, root.name,
                                                 relative_path, text, timeout_s)
    finally:
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
    return {"server": "pyright", "path": relative_path, "diagnostics": diagnostics,
            "sandbox": {"read_only_workspace": True,
                        "network": "network socket access denied by seccomp; anonymous local IPC allowed only for TypeScript"}}


__all__ = ["discover_servers", "network_deny_bootstrap", "pyright_diagnostics",
           "pyright_workspace_symbols"]
